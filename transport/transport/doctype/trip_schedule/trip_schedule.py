# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, getdate

from transport.transport.utils import check_sales_order_exists

SINGLE_TIME = "Single Time"
WEEKDAY_FIELDS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


class TripSchedule(Document):
	def validate(self):
		if self.effective_to and getdate(self.effective_to) < getdate(self.effective_from):
			frappe.throw(_("Effective To cannot be before Effective From."))

		# A single-time schedule runs on its From Date alone, whatever day that is.
		if self.schedule_type != SINGLE_TIME and not any(self.get(day) for day in WEEKDAY_FIELDS):
			frappe.throw(_("Select at least one day of the week."))

	@frappe.whitelist()
	def generate_trips(self, from_date=None, to_date=None):
		# Checked once up front rather than letting the first Trip.insert()
		# throw partway through a batch, leaving a half-generated range behind.
		check_sales_order_exists(self.project)

		route = frappe.get_doc("Route", self.route)

		from_date = getdate(from_date) if from_date else self.next_generation_start()
		to_date = getdate(to_date) if to_date else (getdate(self.effective_to) if self.effective_to else from_date)

		if self.schedule_type == SINGLE_TIME:
			# One day: the From Date. A range typed into the dialog is ignored.
			from_date = to_date = getdate(self.effective_from)

		if self.effective_to:
			to_date = min(to_date, getdate(self.effective_to))
		if from_date < getdate(self.effective_from):
			from_date = getdate(self.effective_from)

		if from_date > to_date:
			return {"created": 0, "message": _("Nothing to generate - the range is already covered.")}

		created = 0
		self._unassigned = 0
		cursor = from_date
		while cursor <= to_date:
			if self.schedule_type == SINGLE_TIME or self.get(cursor.strftime("%A").lower()):
				created += self.create_trips_for_date(cursor, route)
			cursor = add_days(cursor, 1)

		self.db_set("last_generated_till", to_date)
		return {
			"created": created,
			"unassigned": self._unassigned,
			"from_date": from_date,
			"to_date": to_date,
		}

	def next_generation_start(self):
		if self.last_generated_till:
			return add_days(getdate(self.last_generated_till), 1)
		return getdate(self.effective_from)

	def create_trips_for_date(self, trip_date, route):
		created = 0
		legs = []
		if self.generate_pickup_leg:
			legs.append(("Pickup", route.pickup_time, route.from_place, route.to_place))
		if self.generate_drop_leg:
			legs.append(("Drop", route.drop_time, route.to_place, route.from_place))

		for direction, scheduled_time, from_place, to_place in legs:
			if frappe.db.exists(
				"Trip", {"trip_schedule": self.name, "trip_date": trip_date, "direction": direction}
			):
				continue

			values = {
				"doctype": "Trip",
				"trip_schedule": self.name,
				"project": self.project,
				"route": self.route,
				"direction": direction,
				"trip_date": trip_date,
				"scheduled_time": scheduled_time,
				"from_place": from_place,
				"to_place": to_place,
				"shift": self.shift,
				"no_of_passengers": self.no_of_passengers,
			}

			# The schedule's default vehicle and driver are what lets a month be
			# assigned once. A day where they clash - the driver is already on
			# another Trip at that time, say - still gets its Trip, just left
			# unassigned for Operations, rather than the whole batch failing
			# part-way and the day being skipped for good.
			if self.vehicle or self.driver:
				try:
					frappe.get_doc({**values, "vehicle": self.vehicle, "driver": self.driver}).insert()
					created += 1
					continue
				except frappe.ValidationError:
					self._unassigned += 1

			frappe.get_doc(values).insert()
			created += 1

		return created
