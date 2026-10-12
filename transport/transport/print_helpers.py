# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

"""Data for print formats - Jinja is for layout, so the day-by-day grouping the
client's timesheet needs is done here and handed to the template."""

import calendar

import frappe
from frappe.utils import add_days, date_diff, format_time, getdate

from transport.transport.utils import PUBLIC_HOLIDAY, get_project_holiday_kind


def _clock(value):
	"""A Time as the client writes it on the sheet: 5.30 AM."""
	if not value:
		return ""
	return format_time(value, "h.mm a").upper()


def driver_names_from(rows):
	"""The drivers on the trip lines, by name. A timesheet saved before Drivers was
	added to it has nothing stored, and the sheet must not print a blank where a
	name is known."""
	ids = list(dict.fromkeys(r.driver for r in rows if r.driver))
	if not ids:
		return ""
	names = dict(frappe.get_all("Driver", filters={"name": ("in", ids)}, fields=["name", "full_name"], as_list=True))
	return ", ".join(names.get(i) or i for i in ids)


def get_timesheet_matrix(doc):
	"""The client's monthly timesheet, one row per calendar day of the period:
	the day's pickup and drop-off times, any additional trips, and a remark
	(SAT / SUN / PH, plus whatever the office or driver wrote on the trip).

	The header carries what the sheet opens with: client, vehicle type, the trips
	covered, and the drivers' names. Sundays, Saturdays and public holidays are
	flagged so the template can bold them, as the client's sheet does."""
	rows = list(doc.get("trips") or [])
	trip_names = [r.trip for r in rows if r.trip]
	remarks = {}
	if trip_names:
		for t in frappe.get_all("Trip", filters={"name": ("in", trip_names)}, fields=["name", "remarks", "driver_remarks", "shift"]):
			remarks[t.name] = " / ".join(x for x in (t.remarks, t.driver_remarks) if x)

	by_day = {}
	for r in rows:
		by_day.setdefault(getdate(r.trip_date), []).append(r)

	start, end = getdate(doc.period_from), getdate(doc.period_to)
	days = []
	for offset in range(date_diff(end, start) + 1):
		day = add_days(start, offset)
		legs = sorted(by_day.get(day, []), key=lambda r: str(r.actual_start_time or r.scheduled_time or ""))
		regular = [r for r in legs if not r.is_additional]
		extra = [r for r in legs if r.is_additional]

		def times(items, direction):
			return [_clock(r.actual_start_time or r.scheduled_time) for r in items if r.direction == direction]

		tags = []
		weekday = day.weekday()
		if weekday == 5:
			tags.append("SAT")
		if weekday == 6:
			tags.append("SUN")
		kind = get_project_holiday_kind(doc.project, day)
		if kind == PUBLIC_HOLIDAY:
			tags.append("PH")
		notes = [remarks[r.trip] for r in legs if r.trip and remarks.get(r.trip)]

		days.append(
			{
				"sl": offset + 1,
				"date": day.strftime("%d-%m-%y"),
				"weekday": calendar.day_abbr[weekday].upper(),
				"pickup": "<br>".join(times(regular, "Pickup")),
				"drop": "<br>".join(times(regular, "Drop")),
				"additional": "<br>".join(
					f"{_clock(r.actual_start_time or r.scheduled_time)} ({r.direction.lower()})" for r in extra
				),
				"remarks": " ".join(tags + notes),
				"is_off": weekday >= 5 or kind is not None,
				"has_trips": bool(legs),
			}
		)

	vehicles = frappe.get_all(
		"Rental Vehicle",
		filters={"name": ("in", list({r.vehicle for r in rows if r.vehicle}) or [""])},
		fields=["name", "seating_capacity", "vehicle_type"],
	)
	vehicle_types = ", ".join(
		dict.fromkeys(
			(f"{v.seating_capacity}-SEATER" if v.seating_capacity else (v.vehicle_type or v.name)).upper() for v in vehicles
		)
	)
	routes = list(dict.fromkeys(r.route for r in rows if r.route))
	route_names = [frappe.db.get_value("Route", r, "route_name") or r for r in routes]

	return {
		"month_label": f"{calendar.month_name[start.month].upper()} {start.year}",
		"days": days,
		"vehicle_types": vehicle_types,
		"trips_description": " / ".join(route_names),
		"drivers": doc.driver_names or driver_names_from(rows),
		"client": frappe.db.get_value("Customer", doc.customer, "customer_name") or doc.customer,
		"project_name": frappe.db.get_value("Project", doc.project, "project_name") or doc.project,
	}
