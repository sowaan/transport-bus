# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

"""A fine as the portal reported it, before it becomes a real record.

Fetched rows land here rather than straight into Transport Traffic Fine so a
mapping mistake, a mis-matched vehicle or an unexpected response shape can be
seen and corrected without having already created accounting records. The raw
payload is kept alongside so a bad mapping can be diagnosed later without
re-querying the portal.
"""

import frappe
from frappe import _
from frappe.model.document import Document


class TrafficFineStaging(Document):
	def validate(self):
		self.flag_if_already_known()
	
	def after_save(self):
		if not self.is_invoiced:
			self.create_purchase_invoice()


	def flag_if_already_known(self):
		"""Mark rows we have already recorded, so re-running a sync produces
		no duplicates. Identity is (portal, ticket number) - ticket numbers are
		only unique within the issuing authority."""
		if self.status not in ("New", "Duplicate") or not self.ticket_number:
			return

		existing = frappe.db.exists(
			"Transport Traffic Fine",
			{"ticket_number": self.ticket_number, "source_portal": self.portal},
		)
		if existing:
			self.status = "Duplicate"
			self.transport_traffic_fine = existing

	

	@frappe.whitelist()
	def create_purchase_invoice(self):

        # Prevent duplicate invoice creation
		if self.is_invoiced:
			frappe.throw("A Purchase Invoice has already been created for this fine.")

        # ---------------------------------------------------------
        # CONFIGURATION
        # ---------------------------------------------------------

		SUPPLIER = "Ability Trading Llc"
		ITEM_CODE = "E-IDS-20"

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

		purchase_invoice = frappe.get_doc({
			"doctype": "Purchase Invoice",

			"supplier": SUPPLIER,

			"bill_no": self.name,

			"items": [
				{
					"item_code": ITEM_CODE,
					"qty": 1,
					"rate": self.amount,

					"description": (
						f"Traffic Fine\n"
						f"Ticket Number: {self.ticket_number}\n"
						f"Fine Type: {self.fine_type}\n"
						f"Plate: {self.plate}\n"
						# f"Location: {self.location}\n"
						# f"Violation Date: {self.date_time}"
					)
				}
			]
		})

		purchase_invoice.insert()
		# purchase_invoice.submit()

		# ---------------------------------------------------------
		# MARK FINE AS INVOICED
		# ---------------------------------------------------------

		self.db_set("is_invoiced", 1)

		frappe.msgprint(
			f"Purchase Invoice {purchase_invoice.name} created successfully."
		)

		return purchase_invoice.name