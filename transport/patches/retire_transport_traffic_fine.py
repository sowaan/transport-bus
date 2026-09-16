"""Retire Transport Traffic Fine into Traffic Fine Staging.

Two doctypes described the same fine. A fetch wrote a staging row, and a person
pressed Promote to copy it into a Transport Traffic Fine, which was then the
record accounting and the black-points chain worked on. Everything after the
copy - responsibility, payment, VAT, the Driver Incident - happened on the
second document, while every later fetch kept updating the first. The two drift
by construction, and the copy is what made promotion a step somebody could
forget. Promotion is gone; the staged row is the fine.

What this patch has to get right, in order:

1. **Existing staging rows must satisfy the fields that came across as
   mandatory.** `status`, `responsibility` and `source` are `reqd` now, and the
   68 rows on the first bench to run this had `responsibility` and `source`
   empty and `status` holding the retired staging vocabulary ("New",
   "Promoted"). Those values are not in the new option set, so a row would fail
   validation before anything could fix it.

2. **Only the decisions come across from the old fine.** The staging row already
   holds what the portal reported. A blanket field copy would overwrite `amount`,
   `description` and `raw_payload` with whatever the promoted copy happened to
   carry - which is the older reading, since fetches kept enriching staging and
   never touched the promotion.

3. **Nothing may be written by saving a document.** `after_save` on Traffic Fine
   Staging creates a Purchase Invoice, and most rows are not invoiced - saving
   them to correct a column would raise a draft invoice per row. The controller
   also refuses to do that while `frappe.flags.in_patch` is set, so this is
   belt and braces; the SQL here is the belt.
"""

import frappe

OLD = "Transport Traffic Fine"
NEW = "Traffic Fine Staging"
NEW_TABLE = f"`tab{NEW}`"

VALID_STATUS = ("Unpaid", "Paid", "Disputed", "Cancelled")

# The human decisions, and the operational links the portal never reports.
# Deliberately excludes amount / discounted_amount / description / fine_type /
# fine_location / ticket_type / portal_status / black_points - see note 2 above.
# `rental_agreement` is not here because the field is not on Traffic Fine Staging
# at all. fleetify's own Traffic Fine is hard-wired to a Rental Agreement, which
# is what made it unusable for this app: corporate trips are supplied with a
# driver on a monthly contract and have no rental agreement to point at. The
# retired doctype carried the field anyway and never once filled it in.
# `source` is deliberately NOT carried. `normalise_staging_rows` derives it from
# `raw_payload`, which is evidence the portal actually answered; the old fine's
# own `source` is whatever a person typed. Carrying it would let a hand-created
# fine that happens to match a staged row by ticket identity overwrite the
# stronger signal with the weaker one.
CARRIED = (
	"status",
	"responsibility",
	"add_vat",
	"vat_amount",
	"total_cost",
	"black_points_on_hold",
	"black_points_applied",
	"driver_incident",
	"trip",
	"driver",
	"project",
	"customer",
	"owning_company",
	"attachment",
)


def execute():
	if not frappe.db.table_exists(NEW):
		return

	normalise_staging_rows()

	if frappe.db.exists("DocType", OLD) and frappe.db.table_exists(OLD):
		merge_old_fines()
		frappe.delete_doc("DocType", OLD, force=True, ignore_missing=True)

	# delete_doc removes the DocType and its fields but leaves the table
	# standing, so it is dropped here - and deliberately outside the branch
	# above, keyed on the doctype being gone rather than on this run having
	# removed it. A run that got as far as deleting the doctype and no further
	# would otherwise skip the drop forever on the retry, and the table left
	# behind is a second, unreachable copy of every fine just merged: the exact
	# divergence this patch exists to end, only now invisible.
	if not frappe.db.exists("DocType", OLD):
		frappe.db.sql_ddl(f"drop table if exists `tab{OLD}`")

	frappe.clear_cache(doctype=NEW)
	frappe.db.commit()


def normalise_staging_rows():
	"""Give every existing row a valid value in the newly mandatory fields."""
	default_responsibility = (
		frappe.db.get_single_value("Transport Settings", "imported_fine_responsibility") or "Company"
	)

	# The staging lifecycle (New / Promoted / Ignored / Duplicate) went with
	# promotion. All of its values say the same thing about the fine itself:
	# nobody has recorded it as settled.
	frappe.db.sql(
		f"update {NEW_TABLE} set status = 'Unpaid' where status is null or status not in %s",
		(VALID_STATUS,),
	)
	# `source` cannot be backfilled by looking for an empty value. The column is
	# created in the same migrate that runs this patch, with a default of
	# "Manual", so MariaDB writes that default into every existing row - by the
	# time this runs there is nothing blank left to find, and all 68 rows on the
	# first bench to run it were mislabelled as hand-entered.
	#
	# `raw_payload` is the evidence instead, and it is evidence rather than a
	# guess: it only holds anything because a portal returned it. `sync_run` is
	# not usable for this - the client-fetch path leaves it empty, and it was set
	# on 15 of those 68 rows.
	frappe.db.sql(
		f"""update {NEW_TABLE} set source = 'Portal Sync'
			where coalesce(raw_payload, '') <> '' and coalesce(source, '') in ('', 'Manual')"""
	)
	frappe.db.sql(
		f"update {NEW_TABLE} set source = 'Manual' where coalesce(raw_payload, '') = '' and coalesce(source, '') = ''"
	)
	frappe.db.sql(
		f"update {NEW_TABLE} set responsibility = %s where coalesce(responsibility, '') = ''",
		default_responsibility,
	)
	# Every row that predates this patch was fetched, and its points are held for
	# the same reason a freshly fetched one's are: nobody has confirmed the
	# driver. Applying them now would blacklist retroactively off portal data.
	frappe.db.sql(f"update {NEW_TABLE} set black_points_on_hold = 1 where black_points_on_hold is null")
	frappe.db.sql(f"update {NEW_TABLE} set add_vat = 0 where add_vat is null")
	frappe.db.sql(f"update {NEW_TABLE} set vat_amount = 0 where vat_amount is null")
	frappe.db.sql(
		f"""update {NEW_TABLE}
			set total_cost = coalesce(amount, 0) + coalesce(vat_amount, 0)
			where coalesce(total_cost, 0) = 0"""
	)


def merge_old_fines():
	for fine in frappe.db.sql(f"select * from `tab{OLD}`", as_dict=True):
		staged = find_staged_row(fine)
		staged = staged or create_staged_row(fine)
		if not staged:
			continue

		carry_decisions(fine, staged)
		# The incident's audit trail has to keep pointing at a real fine.
		frappe.db.sql(
			"update `tabDriver Incident` set source_traffic_fine = %s where source_traffic_fine = %s",
			(staged, fine.name),
		)


def find_staged_row(fine):
	"""The row this fine was promoted from, if it is still here.

	The back-link is the authoritative answer, and it is read in SQL because the
	field it lived in has been removed from the doctype - Frappe leaves the
	column behind, which is exactly what makes this recoverable. Identity
	(portal, ticket number) is the fallback for a row whose link was never set;
	both agreed on every record of the bench this was written against.
	"""
	if "transport_traffic_fine" in frappe.db.get_table_columns(NEW):
		linked = frappe.db.sql(
			f"select name from {NEW_TABLE} where transport_traffic_fine = %s limit 1", fine.name
		)
		if linked:
			return linked[0][0]

	if not (fine.ticket_number and fine.source_portal):
		return None

	match = frappe.db.sql(
		f"select name from {NEW_TABLE} where ticket_number = %s and portal = %s limit 1",
		(fine.ticket_number, fine.source_portal),
	)
	return match[0][0] if match else None


def create_staged_row(fine):
	"""A fine that was never staged - entered by hand, or staged and then
	deleted. It still has to survive the retirement, so it becomes a row here.

	`portal` and `ticket_number` are mandatory only for Portal Sync rows, which
	is what lets a hand-entered fine with neither come across intact.
	"""
	doc = frappe.get_doc(
		{
			"doctype": NEW,
			"portal": fine.source_portal,
			"ticket_number": fine.ticket_number,
			"vehicle": fine.vehicle,
			"plate": fine.plate_number,
			"fine_datetime": fine.date_time,
			"amount": fine.amount,
			"discounted_amount": fine.discounted_amount,
			"fine_type": fine.fine_type,
			"fine_location": fine.fine_location,
			"ticket_type": fine.ticket_type,
			"portal_status": fine.portal_status,
			"black_points": fine.black_points,
			"description": fine.description,
			"source": fine.source or "Manual",
			"status": fine.status if fine.status in VALID_STATUS else "Unpaid",
			"responsibility": fine.responsibility or "Company",
			# Carried as-is: a fine already marked applied must not open a second
			# Driver Incident when this row is saved.
			"black_points_applied": fine.black_points_applied,
			"black_points_on_hold": fine.black_points_on_hold,
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


def carry_decisions(fine, staged):
	updates = {field: fine.get(field) for field in CARRIED if fine.get(field) not in (None, "")}
	if not updates:
		return

	keys = ", ".join(f"`{field}` = %s" for field in updates)
	frappe.db.sql(
		f"update {NEW_TABLE} set {keys} where name = %s", (*updates.values(), staged)
	)
