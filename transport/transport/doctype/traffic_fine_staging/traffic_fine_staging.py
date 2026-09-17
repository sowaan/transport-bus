# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

"""A fine, from the portal that reported it through to the invoice that pays it.

This used to be only the landing area for a fetched row, which a person then
promoted into a separate Transport Traffic Fine. That second doctype has been
retired and everything it carried lives here, so the row a fetch writes and the
record accounting works on are the same document. Nothing has to be promoted,
and the two can no longer disagree about the same fine.

What came across, and why each piece matters:

* **Assignment** - Trip, Driver, Project, Customer, and the three-way
  `responsibility` the source document calls for. fleetify's own Traffic Fine is
  hard-wired to a Rental Agreement and expresses this as a `billed_to_customer`
  boolean; corporate trips have no agreement at all and need the three-way split.
* **VAT**, computed but off by default - see `add_vat`.
* **The black-points chain** - paying a Driver-responsibility fine opens a
  Driver Incident, which is what accumulates towards blacklisting. That loop is
  the reason this is a record with a lifecycle rather than a queue.

`raw_payload` is still kept alongside, so a bad mapping can be diagnosed later
without re-querying the portal.
"""

import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import escape_html, flt

VAT_RATE = 0.05


class TrafficFineStaging(Document):
	def validate(self):
		self.calculate_vat()
		self.check_duplicate_ticket()

	def on_update(self):
		self.apply_black_points()

	def after_save(self):
		# A patch must never raise accounting documents as a side effect of
		# touching a row. `run_patches` sets this flag for the whole run
		# (frappe/modules/patch_handler.py:233), so a migration that backfills a
		# column or merges a retired doctype in cannot silently create an
		# invoice per row - there are 59 uninvoiced rows on this bench alone.
		if frappe.flags.in_patch:
			return

		if not self.is_invoiced:
			self.create_purchase_invoice()

	def check_duplicate_ticket(self):
		"""A ticket number identifies a fine, but only within the authority that
		issued it - two emirates can legitimately issue the same number. The
		identity of a fine is therefore (portal, ticket number).

		Enforced here rather than by a database unique index on purpose: Frappe
		stores an empty Data field as '' rather than NULL, so a unique index
		would treat every blank ticket number as a collision and block a second
		hand-entered fine that has not been given one yet.

		`_stage_fine` looks the same pair up before inserting, which is what
		makes re-running a sync idempotent. This is the backstop for the rows a
		person creates or edits by hand, where nothing has looked first.
		"""
		if not self.ticket_number:
			return

		duplicate = frappe.db.exists(
			"Traffic Fine Staging",
			{
				"ticket_number": self.ticket_number,
				"portal": self.portal or ("in", ("", None)),
				"name": ("!=", self.name or ""),
			},
		)
		if duplicate:
			frappe.throw(
				_("Ticket {0} is already recorded on {1}{2}.").format(
					self.ticket_number,
					duplicate,
					_(" for the same portal") if self.portal else "",
				),
				title=_("Duplicate Fine"),
			)

	def calculate_vat(self):
		self.vat_amount = flt(self.amount) * VAT_RATE if self.add_vat else 0
		self.total_cost = flt(self.amount) + flt(self.vat_amount)

	def apply_black_points(self):
		if self.black_points_on_hold:
			# Fetched fines arrive already marked Paid by some portals. Without
			# this hold, importing a driver's fine history would satisfy the
			# condition below on the very first save and blacklist them
			# retroactively for fines settled long ago. A person clears the hold
			# once they have confirmed the driver is genuinely responsible.
			return
		if self.black_points_applied or self.responsibility != "Driver" or self.status != "Paid":
			return
		if not self.driver:
			return

		# The authority's own count wins when we have it. The Transport Settings
		# figure is a flat default for hand-entered fines, and applying it to a
		# fetched one would record a 12-point violation as a 2-point one -
		# understating exactly the fines that matter most for blacklisting.
		points = self.black_points or frappe.db.get_single_value(
			"Transport Settings", "black_points_per_fine"
		) or 0
		incident = frappe.get_doc(
			{
				"doctype": "Driver Incident",
				"driver": self.driver,
				"trip": self.trip,
				"incident_type": "Traffic Fine",
				"description": _("Traffic Fine {0} ({1}) - {2}").format(
					self.ticket_number or self.name, self.fine_type or "", self.name
				),
				"black_points": points,
				"source_traffic_fine": self.name,
			}
		)
		incident.insert(ignore_permissions=True)

		self.db_set({"black_points_applied": 1, "driver_incident": incident.name})

	@frappe.whitelist()
	def create_purchase_invoice(self):

        # Prevent duplicate invoice creation
		if self.is_invoiced:
			frappe.throw("A Purchase Invoice has already been created for this fine.")

        # ---------------------------------------------------------
        # CONFIGURATION
        # ---------------------------------------------------------

		SUPPLIER = self.supplier 
		ITEM_CODE = "E-EPE-007"  # Hardcoded item code for traffic fines

		# ---------------------------------------------------------
		# VALIDATION
		# ---------------------------------------------------------

		if not self.amount:
			frappe.throw("Fine amount is missing.")

		if not frappe.db.exists("Supplier", SUPPLIER):
			frappe.throw(
				f"Supplier '{SUPPLIER}' does not exist."
			)

		if not frappe.db.exists("Item", ITEM_CODE):
			frappe.throw(
				f"Item '{ITEM_CODE}' does not exist."
			)

		# ---------------------------------------------------------
		# CREATE PURCHASE INVOICE
		# ---------------------------------------------------------
		dumps = json.loads(self.raw_payload)
		# the source where the fine was fetched from, e.g. "RTA" or "AD Police"
		row = dumps.get("row") or {}
		source = row.get("Source") or row.get("source") or "N/A"

		purchase_invoice = frappe.get_doc({
			"doctype": "Purchase Invoice",

			"supplier": SUPPLIER,
			"bill_no": self.name,
			"custom_portal": self.portal,
			"items": [
				{
					"item_code": ITEM_CODE,
					"qty": 1,
					"rate": self.amount,

					# Description is a Text Editor (HTML) field, so line breaks
					# have to be <br> - a "\n" just collapses into whitespace.
					"description": "<br>".join(
						[
							f"Description: {escape_html(self.description or '')}",
							f"Ticket Number: {escape_html(self.ticket_number or '')}",
							f"Fine Type: {escape_html(self.fine_type or '')}",
							f"Car: {escape_html(dumps.get('vehicle_description') or 'N/A')}",
							f"Source: {escape_html(source)}",
						]
					)
				}
			]
		})
		# purchase invoice in draft state, not submitted yet, so that it can be reviewed and approved before submission
		purchase_invoice.insert()

		# ---------------------------------------------------------
		# MARK FINE AS INVOICED
		# ---------------------------------------------------------

		self.db_set("is_invoiced", 1)

		frappe.msgprint(
			f"Purchase Invoice {purchase_invoice.name} created successfully."
		)

		return purchase_invoice.name