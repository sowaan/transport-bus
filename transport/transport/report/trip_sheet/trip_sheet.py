# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import cint, flt

from transport.transport.utils import get_project_holiday_kind

HMV_PREFIX = "HMV"


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = get_columns()
	data = get_data(filters)
	return columns, data


def get_columns():
	return [
		{"label": _("Date"), "fieldname": "trip_date", "fieldtype": "Date", "width": 100},
		{"label": _("Customer Name"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 160},
		{"label": _("Project"), "fieldname": "project", "fieldtype": "Link", "options": "Project", "width": 120},
		{"label": _("From"), "fieldname": "from_place", "fieldtype": "Link", "options": "Place", "width": 150},
		{"label": _("To"), "fieldname": "to_place", "fieldtype": "Link", "options": "Place", "width": 150},
		{"label": _("Pickup/Drop"), "fieldname": "direction", "fieldtype": "Data", "width": 90},
		{"label": _("Time"), "fieldname": "scheduled_time", "fieldtype": "Time", "width": 90},
		{"label": _("Driver"), "fieldname": "driver_name", "fieldtype": "Data", "width": 120},
		{"label": _("Vehicle"), "fieldname": "vehicle", "fieldtype": "Link", "options": "Rental Vehicle", "width": 110},
		{"label": _("Vehicle Type"), "fieldname": "vehicle_type_text", "fieldtype": "Data", "width": 130},
		{"label": _("Class"), "fieldname": "vehicle_class", "fieldtype": "Data", "width": 70},
		{"label": _("Shift"), "fieldname": "shift", "fieldtype": "Data", "width": 80},
		{"label": _("Duty"), "fieldname": "duty_mark", "fieldtype": "Data", "width": 60},
		{"label": _("OT"), "fieldname": "ot_mark", "fieldtype": "Data", "width": 60},
		# Why a trip counts as overtime, in the client's own terms: more than 5 trips
		# (HMV), more than 7 (LMV), more than 10 or 12 hours for hour-basis drivers.
		{"label": _("OT Because"), "fieldname": "ot_reason", "fieldtype": "Data", "width": 160},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 90},
		# The source trip-sheet spreadsheet keeps two separate remarks columns -
		# the office's own "Duty Remarks" and whatever the driver wrote in.
		{"label": _("Duty Remarks"), "fieldname": "remarks", "fieldtype": "Data", "width": 180},
		{"label": _("Driver's Remarks"), "fieldname": "driver_remarks", "fieldtype": "Data", "width": 180},
	]


def get_data(filters):
	conditions, values = ["1=1"], {}

	if filters.get("project"):
		conditions.append("t.project = %(project)s")
		values["project"] = filters.project
	if filters.get("trip_date"):
		conditions.append("t.trip_date = %(trip_date)s")
		values["trip_date"] = filters.trip_date
	elif filters.get("from_date") and filters.get("to_date"):
		conditions.append("t.trip_date between %(from_date)s and %(to_date)s")
		values["from_date"] = filters.from_date
		values["to_date"] = filters.to_date
	if filters.get("vehicle"):
		conditions.append("t.vehicle = %(vehicle)s")
		values["vehicle"] = filters.vehicle
	if filters.get("driver"):
		conditions.append("t.driver = %(driver)s")
		values["driver"] = filters.driver
	if filters.get("customer"):
		conditions.append("t.customer = %(customer)s")
		values["customer"] = filters.customer
	if filters.get("shift"):
		conditions.append("t.shift = %(shift)s")
		values["shift"] = filters.shift

	rows = frappe.db.sql(
		f"""
		select
			t.trip_date, t.customer, t.project, t.from_place, t.to_place, t.direction,
			t.scheduled_time, t.driver, d.full_name as driver_name, t.vehicle,
			t.vehicle_class, t.duty_type, t.status, t.remarks, t.driver_remarks, t.shift, t.duration,
			rv.vehicle_type as rv_type, rv.seating_capacity as rv_seats,
			pr.transport_duty_basis, pr.transport_daily_hours_limit
		from `tabTrip` t
		left join `tabDriver` d on d.name = t.driver
		left join `tabRental Vehicle` rv on rv.name = t.vehicle
		left join `tabProject` pr on pr.name = t.project
		where {" and ".join(conditions)}
		order by t.trip_date, t.scheduled_time
		""",
		values,
		as_dict=True,
	)

	settings = frappe.get_cached_doc("Transport Settings")
	for row in rows:
		row["duty_mark"] = "Duty" if row.duty_type == "Duty" else ""
		row["ot_mark"] = "OT" if row.duty_type == "OT" else ""
		row["vehicle_type_text"] = " ".join(
			filter(None, [_("{0}-seater").format(row.rv_seats) if row.rv_seats else "", row.rv_type])
		)
		row["ot_reason"] = ot_reason(row, settings)

	return rows


def ot_reason(row, settings):
	"""One line saying why a trip is overtime. Mirrors Trip.set_duty_type: a
	weekend or public holiday is always OT; otherwise the Project's duty basis
	decides between the trips-per-day limit and the daily hours limit."""
	if row.duty_type != "OT":
		return ""

	holiday = get_project_holiday_kind(row.project, row.trip_date)
	if holiday:
		return _(holiday)

	if row.transport_duty_basis == "Hour Basis" or (
		not row.transport_duty_basis and settings.ot_basis == "Hours"
	):
		hours = flt(row.transport_daily_hours_limit) or flt(settings.daily_working_hours)
		return _("Over {0} hours in the day").format(f"{hours:g}")

	heavy = (row.vehicle_class or "").startswith(HMV_PREFIX)
	limit = cint(settings.hmv_daily_trip_limit if heavy else settings.lmv_daily_trip_limit)
	return _("Over {0} trips ({1})").format(limit, "HMV" if heavy else "LMV")
