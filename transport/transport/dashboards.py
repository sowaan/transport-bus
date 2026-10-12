# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

"""Backing methods for the "Custom" Number Cards seeded in
transport/fixtures/number_card.json - anything expressible as a single
aggregate on one doctype uses a plain "Document Type" card instead (see
the fixture); these two need real cross-record logic a generic aggregate
can't express."""

import frappe
from frappe.utils import get_first_day, get_last_day, getdate, nowdate

from transport.transport.report.project_profit_and_loss.project_profit_and_loss import (
	get_expenses,
	get_revenue,
)


@frappe.whitelist()
def trips_today_count(filters=None):
	count = frappe.db.count(
		"Trip", {"trip_date": nowdate(), "status": ("not in", ["Rejected", "Cancelled"])}
	)
	return {"value": count}


@frappe.whitelist()
def loss_making_projects_count(filters=None):
	"""This month's standing, not all-time - matches the doc's "Active vs
	Loss-making projects" as a current-state dashboard signal."""
	period = frappe._dict(from_date=get_first_day(nowdate()), to_date=get_last_day(nowdate()))
	project_names = frappe.get_all("Trip", pluck="project", distinct=True)

	count = 0
	for project in project_names:
		if get_expenses(project, period) > get_revenue(project, period):
			count += 1
	return {"value": count}


@frappe.whitelist()
def fleet_utilization_percent(filters=None):
	from_date, to_date = get_first_day(nowdate()), get_last_day(nowdate())
	total_days = (getdate(to_date) - getdate(from_date)).days + 1

	vehicle_names = frappe.get_all("Trip", pluck="vehicle", distinct=True)
	if not vehicle_names:
		return {"value": 0}

	trips = frappe.get_all(
		"Trip",
		filters={
			"vehicle": ("in", vehicle_names),
			"trip_date": ("between", [from_date, to_date]),
			"status": ("not in", ["Rejected", "Cancelled"]),
		},
		fields=["vehicle", "trip_date"],
	)

	active_dates_by_vehicle = {}
	for trip in trips:
		active_dates_by_vehicle.setdefault(trip.vehicle, set()).add(trip.trip_date)

	total_possible = total_days * len(vehicle_names)
	total_active = sum(len(dates) for dates in active_dates_by_vehicle.values())
	percent = (total_active / total_possible * 100) if total_possible else 0
	return {"value": round(percent, 1)}


# --------------------------------------------------------------------------
# Operations - what is happening today
# --------------------------------------------------------------------------

RAN_OR_PLANNED = ("Assigned", "Accepted", "Started", "Completed", "Approved")


def _busy_today(field):
	return set(
		frappe.get_all(
			"Trip",
			filters={"trip_date": nowdate(), "status": ("in", RAN_OR_PLANNED), field: ("is", "set")},
			pluck=field,
		)
	)


@frappe.whitelist()
def drivers_busy_today(filters=None):
	return {"value": len(_busy_today("driver")), "route": ["List", "Trip"], "route_options": {"trip_date": nowdate()}}


@frappe.whitelist()
def drivers_available_today(filters=None):
	active = set(frappe.get_all("Driver", filters={"status": "Active", "is_blacklisted": 0}, pluck="name"))
	return {"value": len(active - _busy_today("driver"))}


@frappe.whitelist()
def vehicles_busy_today(filters=None):
	return {"value": len(_busy_today("vehicle")), "route": ["List", "Trip"], "route_options": {"trip_date": nowdate()}}


@frappe.whitelist()
def vehicles_available_today(filters=None):
	free = set(frappe.get_all("Rental Vehicle", filters={"status": "Available"}, pluck="name"))
	return {"value": len(free - _busy_today("vehicle"))}


@frappe.whitelist()
def trips_not_accepted(filters=None):
	"""Trips offered to a driver who has not answered within the confirmation window
	(Transport Settings), plus any flagged for reallocation. The cron that escalates
	these runs every five minutes, so this is the same list seen from the desk."""
	window = frappe.utils.cint(frappe.db.get_single_value("Transport Settings", "driver_confirmation_window_minutes")) or 5
	cutoff = frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=-window)
	waiting = frappe.get_all(
		"Trip",
		filters={"status": "Assigned", "trip_date": (">=", nowdate()), "assigned_on": ("<", cutoff)},
		pluck="name",
	)
	flagged = frappe.get_all(
		"Trip", filters={"needs_reallocation": 1, "status": ("not in", ["Approved", "Cancelled", "Completed"])}, pluck="name"
	)
	return {"value": len(set(waiting) | set(flagged)), "route": ["List", "Trip"], "route_options": {"status": "Assigned"}}


@frappe.whitelist()
def delayed_trips(filters=None):
	"""Today's trips whose scheduled time has passed without the trip starting."""
	now = frappe.utils.nowtime()
	count = frappe.db.count(
		"Trip",
		{"trip_date": nowdate(), "status": ("in", ["Assigned", "Accepted"]), "scheduled_time": ("<", now)},
	)
	return {"value": count, "route": ["List", "Trip"], "route_options": {"trip_date": nowdate()}}


# --------------------------------------------------------------------------
# Management - the month so far
# --------------------------------------------------------------------------


@frappe.whitelist()
def transport_revenue_this_month(filters=None):
	"""Net of VAT, from submitted invoices raised off a Transport Timesheet."""
	total = frappe.db.sql(
		"""select ifnull(sum(net_total), 0) from `tabSales Invoice`
		   where docstatus = 1 and ifnull(transport_timesheet, '') != '' and posting_date between %s and %s""",
		(get_first_day(nowdate()), get_last_day(nowdate())),
	)[0][0]
	return {"value": total, "fieldtype": "Currency"}


@frappe.whitelist()
def direct_cost_this_month(filters=None):
	"""Approved and booked Trip Expenses plus toll crossings dated this month - the
	costs that can be tied to a trip. Not the company's full cost (no salaries)."""
	start, end = get_first_day(nowdate()), get_last_day(nowdate())
	expenses = frappe.db.sql(
		"""select ifnull(sum(amount), 0) from `tabTrip Expense`
		   where status in ('Approved', 'Booked') and expense_date between %s and %s""",
		(start, end),
	)[0][0]
	tolls = frappe.db.sql(
		"select ifnull(sum(amount), 0) from `tabToll Crossing` where crossed_on >= %s and crossed_on < date_add(%s, interval 1 day)",
		(start, end),
	)[0][0]
	return {"value": (expenses or 0) + (tolls or 0), "fieldtype": "Currency"}


def _recent_activity(field, days=7):
	return set(
		frappe.get_all(
			"Trip",
			filters={
				"trip_date": ("between", [frappe.utils.add_days(nowdate(), -days), nowdate()]),
				"status": ("in", RAN_OR_PLANNED),
				field: ("is", "set"),
			},
			pluck=field,
		)
	)


@frappe.whitelist()
def idle_vehicles(filters=None):
	"""Available vehicles with no trip in the last seven days."""
	available = set(frappe.get_all("Rental Vehicle", filters={"status": "Available"}, pluck="name"))
	return {"value": len(available - _recent_activity("vehicle"))}


@frappe.whitelist()
def idle_drivers(filters=None):
	active = set(frappe.get_all("Driver", filters={"status": "Active", "is_blacklisted": 0}, pluck="name"))
	return {"value": len(active - _recent_activity("driver"))}


@frappe.whitelist()
def documents_expiring_or_expired(filters=None):
	return {
		"value": frappe.db.count("Compliance Document", {"status": ("in", ["Expiring Soon", "Expired"])}),
		"route": ["List", "Compliance Document"],
		"route_options": {"status": ["in", ["Expiring Soon", "Expired"]]},
	}


@frappe.whitelist()
def vehicles_over_fuel_limit(filters=None):
	"""Vehicles that have reached their monthly fuel limit this month."""
	if not frappe.db.has_column("Rental Vehicle", "fuel_limit_alerted_month"):
		return {"value": 0}
	return {"value": frappe.db.count("Rental Vehicle", {"fuel_limit_alerted_month": get_first_day(nowdate()).strftime("%Y-%m")})}


@frappe.whitelist()
def open_transport_requests(filters=None):
	return {
		"value": frappe.db.count("Transport Request", {"status": "Open"}),
		"route": ["List", "Transport Request"],
		"route_options": {"status": "Open"},
	}
