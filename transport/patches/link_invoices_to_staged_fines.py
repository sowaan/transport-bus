"""Move the fine-to-invoice link off `bill_no` and onto a field of our own.

`create_purchase_invoice` used to write the staging id into `bill_no`, which is
ERPNext's field for the number the SUPPLIER put on their document. Two things
were wrong with that. It claimed a field that is not ours, so a real supplier
reference could never be recorded alongside; and the connection was one-way -
from the fine you could not find the invoice, because nothing on the invoice was
a link.

`custom_traffic_fine_staging` is a proper Link now, and every other portal detail
on the invoice fetches through it. This patch reconnects the invoices raised
before it existed, then corrects `is_invoiced` on every fine from what it finds.

`bill_no` is deliberately left as it is. It is wrong, but it is the only record
of which fine an already-submitted invoice was raised from, and a submitted
document is not ours to quietly rewrite. The link is added beside it.

Also seeds `reference_label`, which is what each portal calls a fine's reference
number on its own pages - TAMM says Fine Number where everyone else says Ticket
Number, and an accountant reconciling against the portal should see the same
words on both screens.
"""

import frappe

STAGING = "Traffic Fine Staging"

# Only TAMM differs from the default. Seeded by fetcher key rather than by
# portal name so a renamed portal still gets it.
LABEL_BY_FETCHER = {"tamm": "Fine Number"}
DEFAULT_LABEL = "Ticket Number"


def execute():
	if not frappe.db.table_exists(STAGING):
		return

	# The fields this patch reads do not exist yet. They ship as Custom Field
	# fixtures, and `frappe.migrate` syncs fixtures AFTER post_model_sync
	# patches - so on the migrate that first delivers them, this runs against a
	# Purchase Invoice that has no `custom_traffic_fine_staging` column and dies
	# on an unknown column. `ensure_custom_fields` reads the same fixture file
	# and creates whatever is missing; it is idempotent, and it is what the
	# `after_migrate` hook calls anyway, just later than this needs.
	from transport.setup import ensure_custom_fields

	ensure_custom_fields()

	seed_reference_labels()
	resync_fetched_portal_values()
	link_existing_invoices()
	resync_invoiced_flags()
	frappe.db.commit()


def seed_reference_labels():
	"""Name each portal's reference number the way that portal does.

	"Blank means nobody has set it" is not available here. The field ships with
	a default of "Ticket Number", and MariaDB writes a column default into every
	existing row the moment the column is added - so by the time this runs, every
	portal already reads "Ticket Number" and skipping non-blank values would skip
	all of them, including the one portal that needs a different word.

	So the seed is keyed on the fetcher instead, and only overwrites a value
	that is still the shipped default. A label somebody has deliberately changed
	is theirs and is left alone.
	"""
	for portal in frappe.get_all(
		"Traffic Fine Portal", fields=["name", "fetcher_key", "reference_label"]
	):
		label = LABEL_BY_FETCHER.get((portal.fetcher_key or "").lower())
		if not label or portal.reference_label not in ("", None, DEFAULT_LABEL):
			continue
		frappe.db.set_value(
			"Traffic Fine Portal", portal.name, "reference_label", label, update_modified=False
		)


def resync_fetched_portal_values():
	"""Re-read `supplier` and `item` from the portal on every fine.

	Both are `fetch_from` fields, which means they are copied from the portal at
	save time and then never looked at again. When a field's `fetch_from` is
	corrected - or when the portal's own value is filled in later - the rows
	written before that keep whatever they were given, and nothing ever revisits
	them.

	It has already happened three times over. `supplier` spent a few minutes pointed at
	`portal.portal_name`, and every row written in that window stored the
	portal's name as its supplier - a Link to a Supplier that does not exist.
	`item` was added the same way and still holds the portal name on 67 of the
	69 rows on this bench, which is why raising an invoice died inside ERPNext
	with "Item Abu Dhabi Police / TAMM not found" rather than saying that no
	item had been configured.

	Blanking a field is the right outcome when the portal has none. An empty
	item stops the invoice with a message naming what to set and where; a
	dangling one stops it several layers down, in somebody else's code, quoting
	a value nobody recognises as a portal name.

	`reference_label` is here for the same reason and not because it was ever
	wrong: it was added after these rows were written, so every one of them
	fetched nothing and the form had no word to label the number with.
	"""
	fields = ("supplier", "item", "reference_label")
	assignments = ", ".join(f"`{f}` = %s" for f in fields)
	differs = " or ".join(f"coalesce(`{f}`, '') <> coalesce(%s, '')" for f in fields)

	for portal in frappe.get_all(
		"Traffic Fine Portal", fields=["name", *fields]
	):
		values = tuple(portal.get(f) for f in fields)
		frappe.db.sql(
			f"""update `tabTraffic Fine Staging` set {assignments}
				where portal = %s and ({differs})""",
			(*values, portal.name, *values),
		)


def link_existing_invoices():
	"""Point each old invoice at the fine whose id it was carrying in bill_no."""
	invoices = frappe.db.sql(
		"""select name, bill_no from `tabPurchase Invoice`
			where coalesce(custom_traffic_fine_staging, '') = ''
			  and bill_no like 'TR-TFST-%'""",
		as_dict=True,
	)
	for invoice in invoices:
		if not frappe.db.exists(STAGING, invoice.bill_no):
			# The fine was deleted after the invoice was raised. Nothing to link
			# to, and inventing one would be worse than leaving it unlinked.
			continue
		frappe.db.set_value(
			"Purchase Invoice",
			invoice.name,
			"custom_traffic_fine_staging",
			invoice.bill_no,
			update_modified=False,
		)


def resync_invoiced_flags():
	"""Set every fine's flag from whether an invoice actually stands against it.

	Written in SQL, not by saving: `after_save` on a fine raises a Purchase
	Invoice, so correcting a flag through the ORM would bill every fine this
	touches. The controller refuses while `frappe.flags.in_patch` is set, but
	the flag is belt and this is braces.
	"""
	frappe.db.sql(
		"""update `tabTraffic Fine Staging` fine
			set is_invoiced = exists (
				select 1 from `tabPurchase Invoice` pi
				where pi.custom_traffic_fine_staging = fine.name and pi.docstatus <> 2
			)"""
	)
