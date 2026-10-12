# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

"""Attach a Salik / Darb toll crossing to the Trip that made it.

A crossing arrives from the toll portal with a plate and a time and nothing else.
The client's UAT note lists "Salik & Darb charges (toll expenses)" under what the
system must track, and a toll only means something to the business once it is
known which trip, and so which project, it belongs to.

The match is by vehicle and by time:

* **Trip time** - the crossing falls between the trip's actual start and end.
* **Only trip that day** - when the trip has no usable times, or none matched, the
  vehicle ran exactly one trip that day, so the crossing can only be that one's.

Anything else is left unmatched rather than guessed. A trip that has not run
(Draft, Assigned, Accepted, Rejected, Cancelled) is never matched: the vehicle may
have gone anywhere.

**This runs inside the fine sync's ingest**, which commits in batches, so an
exception here would abort a batch of crossings. match_crossing() therefore never
raises: a failure is logged and the crossing is simply left unmatched, for the
daily rematch to try again. It makes one query per crossing and writes with
db.set_value - no save, no hooks, no side effects on the crossing."""

import frappe
from frappe.utils import add_days, add_to_date, get_datetime, getdate, now_datetime

RAN = ("Started", "Completed", "Approved")


def _window(trip_date, start, end):
	"""(start, end) datetimes of a trip's actual run, or None if it has no times."""
	if not (start and end):
		return None
	begin = get_datetime(trip_date) + start
	finish = get_datetime(trip_date) + end
	if finish < begin:
		finish = add_to_date(finish, days=1)  # ran past midnight
	return begin, finish


def find_trip(vehicle, crossed_on):
	"""(trip, project, basis) for a crossing, or None."""
	if not (vehicle and crossed_on):
		return None

	crossed = get_datetime(crossed_on)
	day = getdate(crossed)

	# The day before is included for a trip that began before midnight and was
	# still running when the crossing happened.
	trips = frappe.db.sql(
		"""
		select name, project, trip_date, actual_start_time, actual_end_time
		from `tabTrip`
		where vehicle = %s and trip_date between %s and %s and status in %s
		order by trip_date, actual_start_time
		""",
		(vehicle, add_days(day, -1), day, RAN),
		as_dict=True,
	)

	for trip in trips:
		window = _window(trip.trip_date, trip.actual_start_time, trip.actual_end_time)
		if window and window[0] <= crossed <= window[1]:
			return trip.name, trip.project, "Trip time"

	same_day = [t for t in trips if getdate(t.trip_date) == day]
	if len(same_day) == 1:
		return same_day[0].name, same_day[0].project, "Only trip that day"

	return None


def _match(name, vehicle, crossed_on):
	found = find_trip(vehicle, crossed_on)
	if not found:
		return None

	trip, project, basis = found
	frappe.db.set_value(
		"Toll Crossing", name, {"trip": trip, "project": project, "match_basis": basis}, update_modified=False
	)
	return trip


def match_crossing(doc, method=None):
	"""Toll Crossing after_insert. Never raises - see the module docstring."""
	try:
		if not doc.get("trip"):
			_match(doc.name, doc.get("vehicle"), doc.get("crossed_on"))
	except Exception:
		frappe.log_error(title="Toll Crossing match failed", message=frappe.get_traceback())


def rematch_unmatched(days=14):
	"""Daily: try again on recent crossings that found no trip. A trip's actual
	times are only written when it ends, so a crossing ingested the same day may
	have had nothing to match against yet."""
	since = add_days(now_datetime(), -days)
	matched = 0
	for crossing in frappe.get_all(
		"Toll Crossing",
		filters={"trip": ("is", "not set"), "vehicle": ("is", "set"), "crossed_on": (">=", since)},
		fields=["name", "vehicle", "crossed_on"],
	):
		try:
			if _match(crossing.name, crossing.vehicle, crossing.crossed_on):
				matched += 1
		except Exception:
			frappe.log_error(title="Toll Crossing rematch failed", message=frappe.get_traceback())
	return matched
