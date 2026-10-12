# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

"""The vehicle log: kilometres at the start and end of each month, and what was run
in between - the client's "Vehicle log (Km from start and end of month)".

The readings are the odometer figures drivers (or the office) record when a trip
starts and ends. Opening is the first start reading of the month and closing the
last end reading; a month with no readings is not listed. Trips recorded without an
odometer simply do not contribute, so a month with only some readings understates
the distance - the Trips column shows how many readings it was built from."""

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{"label": _("Month"), "fieldname": "month", "fieldtype": "Data", "width": 90},
		{"label": _("Vehicle"), "fieldname": "vehicle", "fieldtype": "Link", "options": "Rental Vehicle", "width": 120},
		{"label": _("Opening KM"), "fieldname": "opening", "fieldtype": "Float", "width": 100},
		{"label": _("Closing KM"), "fieldname": "closing", "fieldtype": "Float", "width": 100},
		{"label": _("KM Run (closing - opening)"), "fieldname": "run", "fieldtype": "Float", "width": 160},
		{"label": _("KM Summed From Trips"), "fieldname": "trip_km", "fieldtype": "Float", "width": 150},
		{"label": _("Trips With Readings"), "fieldname": "readings", "fieldtype": "Int", "width": 130},
	]


def get_data(filters):
	conditions, values = ["t.status in ('Started', 'Completed', 'Approved')"], {}
	if filters.get("vehicle"):
		conditions.append("t.vehicle = %(vehicle)s")
		values["vehicle"] = filters.vehicle
	if filters.get("from_date"):
		conditions.append("t.trip_date >= %(from_date)s")
		values["from_date"] = filters.from_date
	if filters.get("to_date"):
		conditions.append("t.trip_date <= %(to_date)s")
		values["to_date"] = filters.to_date

	trips = frappe.db.sql(
		f"""
		select t.vehicle, date_format(t.trip_date, '%%Y-%%m') as month, t.trip_date, t.scheduled_time,
			t.start_odometer, t.end_odometer
		from `tabTrip` t
		where {" and ".join(conditions)} and t.vehicle is not null
			and (t.start_odometer is not null or t.end_odometer is not null)
		order by t.vehicle, t.trip_date, t.scheduled_time
		""",
		values,
		as_dict=True,
	)

	grouped = {}
	for t in trips:
		grouped.setdefault((t.month, t.vehicle), []).append(t)

	rows = []
	for (month, vehicle), items in sorted(grouped.items(), reverse=True):
		starts = [t.start_odometer for t in items if t.start_odometer is not None]
		ends = [t.end_odometer for t in items if t.end_odometer is not None]
		opening = flt(starts[0]) if starts else None
		closing = flt(ends[-1]) if ends else None
		both = [t for t in items if t.start_odometer is not None and t.end_odometer is not None and t.end_odometer >= t.start_odometer]
		rows.append(
			{
				"month": month,
				"vehicle": vehicle,
				"opening": opening,
				"closing": closing,
				"run": (closing - opening) if (opening is not None and closing is not None and closing >= opening) else None,
				"trip_km": sum(flt(t.end_odometer) - flt(t.start_odometer) for t in both),
				"readings": len(both),
			}
		)
	return rows
