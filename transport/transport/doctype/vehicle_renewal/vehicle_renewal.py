# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

"""Where a vehicle is in its registration renewal.

The client's UAT note: "Vehicle Renewal - should see the status of vehicle
registration renewal. Mulkiya expiry, passing work, speed certificate, passing
report, insurance, renewal." Those six are the stages, in that order. One
Vehicle Renewal follows one vehicle through them; the list shows each vehicle's
current stage, so "which vehicles are stuck at passing" is a filter.

Completing it does the part that makes the renewal count: the new registration and
insurance expiry dates go onto the vehicle, which feeds Compliance Document, which
is what the reminders read - so the one-month reminder restarts for the new date
without anybody re-keying it. The costs of the steps go onto the vehicle's renewal
fee fields, the ones the company vehicle list prints."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, nowdate

STAGES = (
	"Mulkiya Expiry",
	"Passing Work",
	"Speed Certificate",
	"Passing Report",
	"Insurance",
	"Renewal",
)

# Which vehicle fee a stage's cost belongs to. Passing work, the speed
# certificate and the passing report are all the one "passing fee, commission and
# certificate" column on the client's list.
FEE_FIELDS = {
	"Passing Work": "passing_fee",
	"Speed Certificate": "passing_fee",
	"Passing Report": "passing_fee",
	"Insurance": "insurance_renewal_fee",
	"Renewal": "mulkiya_renewal_fee",
}


class VehicleRenewal(Document):
	def validate(self):
		self.seed_stages()
		self.check_one_in_progress()
		self.total_cost = sum(flt(row.cost) for row in self.stages)
		self.set_current_stage()

		for row in self.stages:
			if row.status == "Done" and not row.done_on:
				row.done_on = nowdate()

	def seed_stages(self):
		if self.stages:
			return
		for stage in STAGES:
			self.append("stages", {"stage": stage, "status": "Pending"})

	def check_one_in_progress(self):
		if self.status != "In Progress":
			return

		clash = frappe.db.exists(
			"Vehicle Renewal", {"vehicle": self.vehicle, "status": "In Progress", "name": ("!=", self.name or "")}
		)
		if clash:
			frappe.throw(_("{0} already has a renewal in progress ({1}).").format(self.vehicle, clash))

	def set_current_stage(self):
		pending = next((row.stage for row in self.stages if row.status != "Done"), None)
		self.current_stage = pending or _("All stages done")

	@frappe.whitelist()
	def complete(self):
		"""Finish the renewal: new dates and fees onto the vehicle."""
		self.check_permission("write")
		if self.status != "In Progress":
			frappe.throw(_("Only a renewal in progress can be completed."))
		if any(row.status != "Done" for row in self.stages):
			frappe.throw(_("Every stage must be Done before the renewal is completed (now at: {0}).").format(self.current_stage))
		if not (self.new_registration_expiry or self.new_insurance_expiry):
			frappe.throw(_("Enter the new registration expiry, or the new insurance expiry, so the vehicle can be updated."))

		vehicle = frappe.get_doc("Rental Vehicle", self.vehicle)
		if self.new_registration_expiry:
			vehicle.registration_expiry = self.new_registration_expiry
		if self.new_insurance_expiry:
			vehicle.insurance_expiry = self.new_insurance_expiry

		fees = {}
		for row in self.stages:
			field = FEE_FIELDS.get(row.stage)
			if field and flt(row.cost):
				fees[field] = fees.get(field, 0) + flt(row.cost)
		for field, amount in fees.items():
			vehicle.set(field, amount)

		vehicle.flags.ignore_permissions = True
		vehicle.save()

		self.db_set("status", "Completed")
		return {"vehicle": vehicle.name, "fees": fees}


@frappe.whitelist()
def start_renewal(vehicle):
	"""Open a renewal for a vehicle, or return the one already open."""
	frappe.has_permission("Vehicle Renewal", "create", throw=True)

	existing = frappe.db.get_value("Vehicle Renewal", {"vehicle": vehicle, "status": "In Progress"}, "name")
	if existing:
		return {"name": existing, "created": False}

	renewal = frappe.get_doc({"doctype": "Vehicle Renewal", "vehicle": vehicle}).insert()
	# The first stage is the trigger - the registration is expiring - so it
	# is done by definition the moment a renewal is opened.
	renewal.stages[0].status = "Done"
	renewal.save()
	return {"name": renewal.name, "created": True}
