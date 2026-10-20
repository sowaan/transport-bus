# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

"""Bills toll crossings: one Purchase Invoice per vehicle, one line per crossing.

The authority (Salik, Darb) is the supplier, so a Purchase Invoice for a
vehicle's tolls is really one per vehicle *per authority* - an invoice has a
single supplier. For the usual case of one authority it is simply one per
vehicle, which is what was asked for.

Each line carries the crossing it bills (`custom_toll_crossing`), and the
crossing carries the invoice back (`purchase_invoice`). The back-link is a stored
column, like `Traffic Fine Staging.is_invoiced`, so a list can filter on it; and
like that flag it is put right from the invoice's own events - cancelling or
deleting the invoice frees its crossings to be billed again.

Nothing here adds tax. A toll's amount is VAT-inclusive (see the Toll Expense
Report) and the invoice takes whatever the item's own tax template says, the
same as a fine's invoice does.
"""

import json
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt, getdate

CROSSING = "Toll Crossing"
SKIP_ALREADY = "already billed"
SKIP_NO_VEHICLE = "no vehicle matched"
SKIP_NO_AMOUNT = "no charge"


def _portal_for(authority):
	"""The Traffic Fine Portal that carries this authority's supplier and item."""
	return frappe.db.get_value(
		"Traffic Fine Portal",
		{"fetcher_key": (authority or "").lower()},
		["name", "supplier", "item"],
		as_dict=True,
	)


def _label(row):
	"""What a crossing line says: where, which way, when."""
	bits = [row.gate, row.direction]
	when = frappe.utils.format_datetime(row.crossed_on, "dd-MMM-yyyy HH:mm") if row.crossed_on else ""
	text = " ".join(b for b in bits if b)
	return f"{row.authority} toll - {text} - {when}".replace(" -  - ", " - ")


@frappe.whitelist(methods=["POST"])
def create_purchase_invoices(names):
	"""Raise Draft Purchase Invoices for the crossings named - one per vehicle.

	`names` is a list of Toll Crossing names (or its JSON): a single one from the
	form, or the rows ticked on the list. Crossings already billed, without a
	matched vehicle or without a charge are left out and reported, never billed
	by guess. Each invoice is its own savepoint, so one that fails does not stop
	the rest. Returns {"invoices": [...], "skipped": [...], "failed": [...]}."""
	if isinstance(names, str):
		names = json.loads(names) if names.strip().startswith("[") else [names]
	names = list(dict.fromkeys(names or []))
	if not names:
		frappe.throw(_("Select at least one Toll Crossing."))

	frappe.has_permission("Purchase Invoice", "create", throw=True)

	rows = frappe.get_all(
		CROSSING,
		filters={"name": ("in", names)},
		fields=["name", "authority", "transaction_id", "crossed_on", "amount", "vehicle",
				"plate_text", "gate", "direction", "purchase_invoice"],
		order_by="crossed_on asc",
	)
	if len(rows) != len(names):
		missing = sorted(set(names) - {r.name for r in rows})
		frappe.throw(_("Toll Crossing not found: {0}").format(", ".join(missing)))

	skipped, groups = [], defaultdict(list)
	for row in rows:
		# Asked of the invoices, not just the stored link: a link left over from
		# before the hooks existed must not be trusted over what stands.
		standing = _standing_invoice(row.name)
		if standing or row.purchase_invoice:
			skipped.append({"name": row.name, "reason": _(SKIP_ALREADY), "invoice": standing or row.purchase_invoice})
		elif not row.vehicle:
			skipped.append({"name": row.name, "reason": _(SKIP_NO_VEHICLE), "plate": row.plate_text})
		elif flt(row.amount) <= 0:
			skipped.append({"name": row.name, "reason": _(SKIP_NO_AMOUNT)})
		else:
			groups[(row.vehicle, row.authority)].append(row)

	invoices, failed = [], []
	for (vehicle, authority), crossings in groups.items():
		portal = _portal_for(authority)
		problem = None
		if not portal or not portal.supplier:
			problem = _("The {0} portal has no supplier set.").format(authority)
		elif not portal.item:
			problem = _("The {0} portal has no item set.").format(authority)
		if problem:
			failed.append({"vehicle": vehicle, "authority": authority, "count": len(crossings), "error": problem})
			continue

		savepoint = "toll_invoice"
		frappe.db.savepoint(savepoint)
		try:
			invoice = _make_invoice(vehicle, authority, crossings, portal)
			invoices.append({"invoice": invoice, "vehicle": vehicle, "authority": authority, "count": len(crossings)})
		except Exception as exc:
			frappe.db.rollback(save_point=savepoint)
			failed.append({"vehicle": vehicle, "authority": authority, "count": len(crossings), "error": str(exc)})
			frappe.log_error(
				title="Toll invoice failed",
				message=f"{vehicle} / {authority}: {[c.name for c in crossings]}\n{frappe.get_traceback()}",
			)

	return {"invoices": invoices, "skipped": skipped, "failed": failed}


def _make_invoice(vehicle, authority, crossings, portal):
	first, last = crossings[0].crossed_on, crossings[-1].crossed_on
	# "Supplier Invoice No" is mandatory on this site and is the supplier's own
	# reference. The authority sends no one number for a batch of crossings, so
	# this names the batch: who, which vehicle, which dates.
	bill_no = f"{authority}-{vehicle}-{getdate(first):%d%m%y}-{getdate(last):%d%m%y}"
	if frappe.db.exists("Purchase Invoice", {"supplier": portal.supplier, "bill_no": bill_no, "docstatus": ("!=", 2)}):
		bill_no = f"{bill_no}-{len(crossings)}-{frappe.generate_hash(length=4)}"

	invoice = frappe.get_doc({
		"doctype": "Purchase Invoice",
		"supplier": portal.supplier,
		"custom_toll_vehicle": vehicle,
		"bill_no": bill_no,
		"bill_date": getdate(last),
		"items": [
			{
				"item_code": portal.item,
				"qty": 1,
				"rate": flt(c.amount),
				"description": frappe.utils.escape_html(_label(c)),
				"custom_toll_crossing": c.name,
			}
			for c in crossings
		],
	})
	invoice.insert()

	# Straight to the column: a Toll Crossing has no save logic to run, and its
	# `modified` should not move for a billing flag.
	for c in crossings:
		frappe.db.set_value(CROSSING, c.name, "purchase_invoice", invoice.name, update_modified=False)
	return invoice.name


def _standing_invoice(crossing):
	"""A Draft or Submitted Purchase Invoice already billing this crossing."""
	found = frappe.db.sql(
		"""select pi.name from `tabPurchase Invoice Item` item
		join `tabPurchase Invoice` pi on pi.name = item.parent
		where item.custom_toll_crossing = %s and pi.docstatus != 2 limit 1""",
		crossing,
	)
	return found[0][0] if found else None


def refresh_crossings_on_cancel(doc, method=None):
	_free_crossings(doc)


def refresh_crossings_on_trash(doc, method=None):
	_free_crossings(doc)


def _free_crossings(invoice):
	"""Clear the back-link on every crossing this invoice billed.

	Only where it still points at this invoice - a crossing since re-billed on a
	newer invoice keeps that one."""
	for item in invoice.get("items") or []:
		crossing = item.get("custom_toll_crossing")
		if crossing and frappe.db.get_value(CROSSING, crossing, "purchase_invoice") == invoice.name:
			frappe.db.set_value(CROSSING, crossing, "purchase_invoice", None, update_modified=False)
