# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

"""A vehicle's condition on one line: the client's "a complete vehicle condition
report must be recorded". Drawn from the inspections already being recorded - the
daily check points, the fortnightly / handover sheet and its damage marks - plus the
last and next service."""

import frappe
from frappe import _
from frappe.utils import add_days, getdate, nowdate

LOOKBACK_DAYS = 30


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{"label": _("Vehicle"), "fieldname": "vehicle", "fieldtype": "Link", "options": "Rental Vehicle", "width": 120},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 110},
		{"label": _("Last Daily Check"), "fieldname": "last_daily", "fieldtype": "Date", "width": 110},
		{"label": _("Poor Points (30d)"), "fieldname": "poor_points", "fieldtype": "Int", "width": 110},
		{"label": _("Fair Points (30d)"), "fieldname": "fair_points", "fieldtype": "Int", "width": 110},
		{"label": _("Worst Point"), "fieldname": "worst_point", "fieldtype": "Data", "width": 200},
		{"label": _("Last Handover Check"), "fieldname": "last_handover", "fieldtype": "Date", "width": 120},
		{"label": _("Exterior"), "fieldname": "exterior", "fieldtype": "Data", "width": 70},
		{"label": _("Interior"), "fieldname": "interior", "fieldtype": "Data", "width": 70},
		{"label": _("Tyres"), "fieldname": "tyres", "fieldtype": "Data", "width": 70},
		{"label": _("Battery"), "fieldname": "battery", "fieldtype": "Data", "width": 70},
		{"label": _("Damage Marks"), "fieldname": "damage_marks", "fieldtype": "Int", "width": 100},
		{"label": _("Last Service"), "fieldname": "last_service", "fieldtype": "Date", "width": 100},
		{"label": _("Next Service"), "fieldname": "next_service", "fieldtype": "Date", "width": 100},
		{"label": _("Condition"), "fieldname": "condition", "fieldtype": "Data", "width": 90},
	]


def get_data(filters):
	conditions, values = ["1=1"], {"since": add_days(getdate(nowdate()), -LOOKBACK_DAYS)}
	if filters.get("vehicle"):
		conditions.append("rv.name = %(vehicle)s")
		values["vehicle"] = filters.vehicle
	if filters.get("company"):
		conditions.append("rv.company = %(company)s")
		values["company"] = filters.company

	vehicles = frappe.db.sql(
		f"select rv.name as vehicle, rv.status from `tabRental Vehicle` rv where {' and '.join(conditions)} order by rv.name",
		values,
		as_dict=True,
	)

	out = []
	for v in vehicles:
		row = frappe._dict(vehicle=v.vehicle, status=v.status)

		daily = frappe.db.sql(
			"""select max(i.inspection_date) from `tabVehicle Inspection` i
			   where i.vehicle = %s and i.inspection_type = 'Daily'""",
			v.vehicle,
		)
		row.last_daily = daily[0][0] if daily else None

		points = frappe.db.sql(
			"""select c.condition, c.check_point from `tabVehicle Inspection Check Point` c
			   join `tabVehicle Inspection` i on i.name = c.parent
			   where i.vehicle = %s and i.inspection_type = 'Daily' and i.inspection_date >= %s
			     and c.condition in ('Poor', 'Fair')""",
			(v.vehicle, values["since"]),
			as_dict=True,
		)
		row.poor_points = sum(1 for p in points if p.condition == "Poor")
		row.fair_points = sum(1 for p in points if p.condition == "Fair")
		counts = {}
		for p in points:
			if p.condition == "Poor":
				counts[p.check_point] = counts.get(p.check_point, 0) + 1
		row.worst_point = max(counts, key=counts.get) if counts else ""

		handover = frappe.db.sql(
			"""select i.name, i.inspection_date, i.exterior_condition, i.interior_condition, i.tyre_condition, i.battery_condition
			   from `tabVehicle Inspection` i
			   where i.vehicle = %s and i.inspection_type in ('Fortnightly', 'Check-In', 'Check-Out')
			   order by i.inspection_date desc, i.creation desc limit 1""",
			v.vehicle,
			as_dict=True,
		)
		if handover:
			h = handover[0]
			row.last_handover = h.inspection_date
			row.exterior, row.interior = h.exterior_condition, h.interior_condition
			row.tyres, row.battery = h.tyre_condition, h.battery_condition
			row.damage_marks = frappe.db.count("Vehicle Inspection Damage Mark", {"parent": h.name})
		else:
			row.damage_marks = 0

		service = frappe.db.sql(
			"""select service_date, next_service_date from `tabService History`
			   where vehicle = %s order by service_date desc, creation desc limit 1""",
			v.vehicle,
			as_dict=True,
		)
		if service:
			row.last_service, row.next_service = service[0].service_date, service[0].next_service_date

		grades = [row.get(k) for k in ("exterior", "interior", "tyres", "battery")]
		if row.poor_points or "Poor" in grades:
			row.condition = "Poor"
		elif row.fair_points or "Fair" in grades or row.damage_marks:
			row.condition = "Fair"
		elif row.last_daily or row.last_handover:
			row.condition = "Good"
		else:
			row.condition = "Not inspected"
		out.append(row)

	if filters.get("condition"):
		out = [r for r in out if r.condition == filters.condition]
	return out
