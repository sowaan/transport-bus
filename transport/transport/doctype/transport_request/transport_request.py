# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

"""An ad-hoc transport request, logged and invoiced at month end.

The client's UAT note: requests keep arriving in the sister companies' WhatsApp
group - "arrange a vehicle with a driver at 9:30 for ...", "vehicle for visa
medical at 2:10 pm" - and at month end each company is invoiced for what it asked
for. Their working sheet has one line per request (date, pick up, drop off, times,
vehicle, driver, KM, rate) and the invoice is a single line, "Transport Request for
the Month July 2026", with VAT worked back out of the total.

This is that sheet as a record: one Transport Request per request as it comes in,
and create_monthly_invoice() turns a company's open requests for a month into one
Sales Invoice.

It is deliberately not a Trip. A Trip belongs to a Project with a Sales Order, a
route and a schedule, and is billed through a Timesheet; these are one-off errands
for companies that have no contract with us, billed by the month."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, get_first_day, get_last_day

ACCOUNTS_ROLES = ("Transport Accounts", "System Manager")


class TransportRequest(Document):
	def validate(self):
		if self.start_time and self.end_time and self.end_time < self.start_time:
			frappe.throw(_("End Time cannot be before Start Time."))
		if flt(self.charge) < 0:
			frappe.throw(_("The charge cannot be negative."))

	def on_trash(self):
		if self.status == "Invoiced":
			frappe.throw(_("This request has been invoiced ({0}); it cannot be deleted.").format(self.sales_invoice))


@frappe.whitelist()
def create_monthly_invoice(customer, month, company=None):
	"""One Sales Invoice for a company's open requests in a calendar month.

	`month` is any date inside the month. Every Open request from that company
	dated in it goes on a single line - "Transport Request for the Month July
	2026" - and is marked Invoiced. When the requests' charges include VAT the tax
	row is switched to "included in rate", so ERPNext works the net amount and the
	VAT back out of the total the way the client's own invoice does (230.00
	becomes 219.05 + 10.95).

	Requests in one invoice must agree on whether VAT is included - the tax
	treatment belongs to the invoice, not to a line - so a mixed month stops and
	says so rather than mis-stating VAT."""
	if not any(role in frappe.get_roles() for role in ACCOUNTS_ROLES):
		frappe.throw(_("Not permitted to invoice Transport Requests."), frappe.PermissionError)

	settings = frappe.get_single("Transport Settings")
	company = company or settings.transport_request_company
	if not company:
		frappe.throw(_("Choose the company to invoice from, or set Invoicing Company in Transport Settings."))
	item = settings.transport_request_item or settings.transport_service_item
	if not item:
		frappe.throw(_("Set the Invoice Item (or the Transport Service Item) in Transport Settings."))

	start, end = get_first_day(month), get_last_day(month)
	requests = frappe.get_all(
		"Transport Request",
		filters={"customer": customer, "status": "Open", "request_date": ("between", [start, end])},
		fields=["name", "charge", "charge_includes_vat", "request_date"],
		order_by="request_date, creation",
	)
	if not requests:
		frappe.throw(_("{0} has no open requests in {1}.").format(customer, frappe.utils.formatdate(start, "MMMM yyyy")))

	inclusive = {bool(r.charge_includes_vat) for r in requests}
	if len(inclusive) > 1:
		frappe.throw(
			_("Some of these requests include VAT and some do not. Make them agree, or invoice them separately."),
			title=_("Mixed VAT treatment"),
		)
	includes_vat = inclusive.pop()

	total = sum(flt(r.charge) for r in requests)
	label = frappe.utils.formatdate(start, "MMMM yyyy")

	invoice = frappe.new_doc("Sales Invoice")
	invoice.update(
		{
			"customer": customer,
			"company": company,
			"posting_date": frappe.utils.nowdate(),
			"set_posting_time": 0,
			"remarks": _("Transport Requests for {0}: {1}").format(label, ", ".join(r.name for r in requests)),
			"items": [
				{
					"item_code": item,
					"qty": 1,
					"rate": total,
					"description": _("Transport Request for the Month {0}").format(label),
				}
			],
		}
	)
	invoice.run_method("set_missing_values")
	if not invoice.get("taxes") and settings.transport_request_tax_template:
		# Neither the customer nor the company carries a default tax template, so
		# VAT would be silently left off an invoice the client expects it on.
		invoice.taxes_and_charges = settings.transport_request_tax_template
		invoice.set_taxes()
	if includes_vat:
		for tax in invoice.get("taxes") or []:
			tax.included_in_print_rate = 1
	invoice.run_method("calculate_taxes_and_totals")
	invoice.insert()

	for r in requests:
		frappe.db.set_value("Transport Request", r.name, {"status": "Invoiced", "sales_invoice": invoice.name})

	return {"invoice": invoice.name, "requests": len(requests), "total": total, "net_total": invoice.net_total}
