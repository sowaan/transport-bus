# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

"""The agreement that follows a transport Sales Order - the step the client called
"customer confirmation".

The client's UAT note: after the customer's Sales Order, at vehicle delivery, handover
or trip start, "Rental Agreement in case of vehicle without Driver & Service
agreement in case of Vehicle with driver. We can add in the place of customer
confirmation." The Sales Order's own workflow (Draft / Pending / Approved) has no
customer-confirmation state, so there was nothing to put it in - hence a document.

This is the **with-driver** one. A vehicle supplied **without** a driver uses the
existing Rental Agreement (fleetify), which the Sales Order form opens with the
customer and company filled in. create_service_agreement() builds this one from the
order so nothing is typed twice."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate


class ServiceAgreement(Document):
	def validate(self):
		if self.start_date and self.end_date and getdate(self.end_date) < getdate(self.start_date):
			frappe.throw(_("Service Ends cannot be before Service Starts."))

		if self.status == "Signed" and not (self.signed_copy and self.signed_on):
			frappe.throw(_("Attach the signed copy and say when it was signed before marking the agreement Signed."))

		self.check_one_per_sales_order()

	def check_one_per_sales_order(self):
		if not self.sales_order or self.status == "Cancelled":
			return

		clash = frappe.db.exists(
			"Service Agreement",
			{"sales_order": self.sales_order, "status": ("!=", "Cancelled"), "name": ("!=", self.name or "")},
		)
		if clash:
			frappe.throw(_("Sales Order {0} already has Service Agreement {1}.").format(self.sales_order, clash))


@frappe.whitelist()
def create_service_agreement(sales_order):
	"""Draft the Service Agreement for a transport Sales Order, or return the one
	that already exists. Everything the order knows is carried over - customer,
	project, dates, locations, value, terms, and the vehicles named on its lines or
	allocated on the Project, each with its usual driver."""
	frappe.has_permission("Service Agreement", "create", throw=True)

	order = frappe.get_doc("Sales Order", sales_order)
	if order.docstatus != 1:
		frappe.throw(_("Submit the Sales Order first."))
	if not order.get("transport_project"):
		frappe.throw(_("This is not a transport Sales Order."))

	existing = frappe.db.get_value(
		"Service Agreement", {"sales_order": sales_order, "status": ("!=", "Cancelled")}, "name"
	)
	if existing:
		return {"name": existing, "created": False}

	project = order.get("project") or order.transport_project

	vehicles = []
	for item in order.items:
		if item.get("transport_vehicle") and item.transport_vehicle not in [v["vehicle"] for v in vehicles]:
			vehicles.append(
				{
					"vehicle": item.transport_vehicle,
					"driver": frappe.db.get_value("Rental Vehicle", item.transport_vehicle, "assigned_driver"),
				}
			)
	if not vehicles:
		for row in frappe.get_all(
			"Transport Project Vehicle",
			filters={"parent": project, "parenttype": "Project"},
			fields=["vehicle", "driver", "shift"],
			order_by="idx",
		):
			vehicles.append({"vehicle": row.vehicle, "driver": row.driver, "shift": row.shift})

	agreement = frappe.get_doc(
		{
			"doctype": "Service Agreement",
			"customer": order.customer,
			"company": order.company,
			"sales_order": order.name,
			"project": project,
			"start_date": order.get("transport_start_date") or order.delivery_date,
			"end_date": order.get("transport_end_date"),
			"handover_date": order.get("transport_start_date") or order.delivery_date,
			"contract_value": order.grand_total,
			"scope_of_service": order.get("transport_locations"),
			"tc_name": order.get("tc_name"),
			"terms": order.get("terms"),
			"vehicles": vehicles,
		}
	).insert()
	return {"name": agreement.name, "created": True}
