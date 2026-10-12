# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

"""Which drivers are over- or under-used - the client's "under / over utilized
drivers". Per driver over the period: trips, days worked, hours, overtime, and the
longest day.

* **Over-utilized** - the average day worked is longer than the daily working hours
  in Transport Settings, or any single day passed the fatigue limit.
* **Under-utilized** - worked fewer than 40% of the days in the period.
* **Balanced** - neither.

Hours are the trips' recorded durations, so a trip with no actual start and end
adds a trip and a day worked but no hours."""

import frappe
from frappe import _
from frappe.utils import add_months, date_diff, flt, getdate, nowdate

UNDER_USED_PCT = 40


def execute(filters=None):
	filters = frappe._dict(filters or {})
	to_date = getdate(filters.get("to_date") or nowdate())
	from_date = getdate(filters.get("from_date") or add_months(to_date, -1))
	return get_columns(), get_data(filters, from_date, to_date)


def get_columns():
	return [
		{"label": _("Driver"), "fieldname": "driver", "fieldtype": "Link", "options": "Driver", "width": 110},
		{"label": _("Name"), "fieldname": "driver_name", "fieldtype": "Data", "width": 160},
		{"label": _("Trips"), "fieldname": "trips", "fieldtype": "Int", "width": 60},
		{"label": _("Days Worked"), "fieldname": "days_worked", "fieldtype": "Int", "width": 95},
		{"label": _("Days Worked %"), "fieldname": "worked_pct", "fieldtype": "Percent", "width": 105},
		{"label": _("Hours"), "fieldname": "hours", "fieldtype": "Float", "precision": 1, "width": 70},
		{"label": _("Avg Hours / Day"), "fieldname": "avg_hours", "fieldtype": "Float", "precision": 1, "width": 110},
		{"label": _("Longest Day (h)"), "fieldname": "max_day_hours", "fieldtype": "Float", "precision": 1, "width": 110},
		{"label": _("OT Trips"), "fieldname": "ot_trips", "fieldtype": "Int", "width": 75},
		{"label": _("OT Hours"), "fieldname": "ot_hours", "fieldtype": "Float", "precision": 1, "width": 80},
		{"label": _("Utilization"), "fieldname": "utilization", "fieldtype": "Data", "width": 110},
	]


def get_data(filters, from_date, to_date):
	days = date_diff(to_date, from_date) + 1
	settings = frappe.get_cached_doc("Transport Settings")
	daily_limit = flt(settings.daily_working_hours) or 10
	fatigue_limit = flt(settings.fatigue_max_driving_hours) or 12

	driver_filter, values = "", {"from_date": from_date, "to_date": to_date}
	if filters.get("driver"):
		driver_filter = "and d.name = %(driver)s"
		values["driver"] = filters.driver

	drivers = frappe.db.sql(
		f"select d.name as driver, d.full_name as driver_name from `tabDriver` d where d.status = 'Active' {driver_filter} order by d.full_name",
		values,
		as_dict=True,
	)
	trips = frappe.db.sql(
		"""select t.driver, t.trip_date, t.duration, t.duty_type from `tabTrip` t
		   where t.status in ('Completed', 'Approved') and t.driver is not null
			and t.trip_date between %(from_date)s and %(to_date)s""",
		values,
		as_dict=True,
	)

	per_driver = {}
	for t in trips:
		per_driver.setdefault(t.driver, []).append(t)

	rows = []
	for d in drivers:
		items = per_driver.get(d.driver, [])
		by_day = {}
		for t in items:
			by_day[t.trip_date] = by_day.get(t.trip_date, 0) + flt(t.duration)

		row = frappe._dict(d)
		row.trips = len(items)
		row.days_worked = len(by_day)
		row.worked_pct = row.days_worked / days * 100 if days else 0
		row.hours = sum(by_day.values())
		row.avg_hours = row.hours / row.days_worked if row.days_worked else 0
		row.max_day_hours = max(by_day.values()) if by_day else 0
		row.ot_trips = sum(1 for t in items if t.duty_type == "OT")
		row.ot_hours = sum(flt(t.duration) for t in items if t.duty_type == "OT")

		if row.avg_hours > daily_limit or row.max_day_hours > fatigue_limit:
			row.utilization = "Over-utilized"
		elif row.worked_pct < UNDER_USED_PCT:
			row.utilization = "Under-utilized"
		else:
			row.utilization = "Balanced"

		if filters.get("utilization") and filters.utilization != row.utilization:
			continue
		rows.append(row)

	order = {"Over-utilized": 0, "Under-utilized": 1, "Balanced": 2}
	rows.sort(key=lambda r: (order[r.utilization], -r.hours))
	return rows
