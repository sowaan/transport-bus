# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

"""Vehicle inspections, in the four forms the client uses.

* **Daily** - the driver's first job of the day: 17 check points, each marked
  Good / Fair / Poor (G / F / P). Some points are checked daily, some weekly,
  some monthly - the frequency is printed beside each, and a weekly or monthly
  point is simply left blank on the days it is not due. One per vehicle per day.
  The Vehicle Inspection Grid report lays a month of these out as the client's
  paper sheet: points down the side, days 1-31 across.
* **Fortnightly** - Operations In-charge, twice a month, as each vehicle comes
  in. The vehicle OUT / IN sheet: handover checklist, damage marks (the S / D / B
  marks drawn on the car outline), fuel and kilometres.
* **Check-Out / Check-In** - the same sheet at delivery to, and return from, a
  customer.

Not wired as a hard gate on Trip creation - the source workflow lists it as an
operational requirement, not one of the "Mandatory System Controls" it
enumerates separately."""

import frappe
from frappe import _
from frappe.model.document import Document

DAILY = "Daily"
HANDOVER_TYPES = ("Fortnightly", "Check-Out", "Check-In")

# The 17 points on the client's daily sheet, in its order, with the frequency it
# prints beside each.
CHECK_POINTS = (
	("Tyres Conditions including spare (Any crack, damage, etc.,)", "Daily"),
	("Hand Brake Condition", "Daily"),
	("Condition of all Lights", "Daily"),
	("Brake Condition", "Daily"),
	("Fire Extinguisher", "Daily"),
	("First Aid Box", "Daily"),
	("Tidiness Of the Vehicle", "Daily"),
	("No Oil Leakage", "Daily"),
	("Pressure Condition all tyres", "Daily"),
	("Working condition of the A/C", "Daily"),
	("Radiator Water Level", "Weekly"),
	("Brake / Engine Oil Level", "Weekly"),
	("Reverse Lights", "Weekly"),
	("Wheel Nut Tight & Tools", "Weekly"),
	("Reflective triangle", "Monthly"),
	("All Seat Belts", "Monthly"),
	("Condition of Emergency Exit", "Monthly"),
)

# The checklist on the vehicle OUT / IN sheet.
HANDOVER_ITEMS = (
	"Vehicle Clean",
	"Wind Shield",
	"Salik Tag",
	"Wing Mirrors",
	"Radio Antenna",
	"Wheel Cups / Cover",
	"Spare Tyre",
	"Wheel Spanner",
	"Tool Kit",
	"Jack",
	"Fire Extinguisher",
	"Seat Clean",
	"Floor Mats",
	"Radio Tape",
	"A/C Controls",
	"Lighter",
	"Registration Copy",
	"Vehicle Agreement Copy",
)

# What a handover-type inspection must record. Check-In / Check-Out keep the
# full set they have always required; the fortnightly sheet has no condition
# grades, only the readings.
HANDOVER_REQUIRED = {
	"Fortnightly": ("odometer_reading", "fuel_level"),
	"Check-Out": (
		"odometer_reading", "fuel_level", "exterior_condition", "interior_condition",
		"tyre_condition", "battery_condition", "photo",
	),
	"Check-In": (
		"odometer_reading", "fuel_level", "exterior_condition", "interior_condition",
		"tyre_condition", "battery_condition", "photo",
	),
}


def default_check_points():
	return [
		{"sl_no": index, "check_point": point, "frequency": frequency}
		for index, (point, frequency) in enumerate(CHECK_POINTS, start=1)
	]


def default_handover_checklist():
	return [{"item": item, "present": 0} for item in HANDOVER_ITEMS]


@frappe.whitelist()
def get_inspection_lists(inspection_type=None):
	"""The rows a new inspection of this type starts with. The desk form fills
	them in as it opens; validate() does the same for API and import."""
	if inspection_type == DAILY:
		return {"check_points": default_check_points(), "handover_checklist": []}
	return {"check_points": [], "handover_checklist": default_handover_checklist()}


class VehicleInspection(Document):
	def validate(self):
		self.seed_lists()
		self.check_one_daily_per_vehicle_per_day()
		self.check_handover_readings()

	def seed_lists(self):
		if self.inspection_type == DAILY:
			if not self.check_points:
				for row in default_check_points():
					self.append("check_points", row)
		elif not self.handover_checklist:
			for row in default_handover_checklist():
				self.append("handover_checklist", row)

	def check_one_daily_per_vehicle_per_day(self):
		if self.inspection_type != DAILY:
			return

		clash = frappe.db.exists(
			"Vehicle Inspection",
			{
				"vehicle": self.vehicle,
				"inspection_date": self.inspection_date,
				"inspection_type": DAILY,
				"name": ("!=", self.name or ""),
			},
		)
		if clash:
			frappe.throw(
				_("{0} already has a daily inspection for {1} ({2}). Open that one instead.").format(
					self.vehicle, frappe.utils.formatdate(self.inspection_date), clash
				)
			)

	def check_handover_readings(self):
		"""Frappe's own `reqd` is off on these fields because a daily inspection
		does not need them, so the handover types are enforced here."""
		missing = [
			self.meta.get_label(fieldname)
			for fieldname in HANDOVER_REQUIRED.get(self.inspection_type, ())
			if self.get(fieldname) in (None, "")
		]
		if missing:
			frappe.throw(
				_("A {0} inspection needs: {1}.").format(self.inspection_type, ", ".join(missing)),
				title=_("Missing details"),
			)
