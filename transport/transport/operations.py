# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

"""Office-side (Transport In-Charge / Operations) trip actions, distinct from
driver_portal.py's driver-facing ones. Approving a Completed trip is what
'hits the timesheet' per the source workflow doc - only Approved trips are
eligible to be pulled onto a Transport Timesheet (see
transport_timesheet.populate_trips)."""

import frappe
from frappe import _
from frappe.utils import flt, now_datetime, nowtime

APPROVER_ROLES = ("Transport In-Charge", "Transport Operations", "System Manager")

# A trip the office may still start. "Accepted" is the driver having agreed to
# it; "Assigned" is the far more common case here, because a driver who is not
# using the portal never presses Accept at all - and that is precisely who this
# action exists for.
STARTABLE_STATUSES = ("Assigned", "Accepted")


@frappe.whitelist()
def approve_trip(trip_name):
	if not any(role in frappe.get_roles() for role in APPROVER_ROLES):
		frappe.throw(_("Not permitted to approve trips."), frappe.PermissionError)

	trip = frappe.get_doc("Trip", trip_name)
	if trip.status != "Completed":
		frappe.throw(_("Only Completed trips can be approved (current status: {0}).").format(trip.status))

	trip.db_set({"status": "Approved", "approved_by": frappe.session.user, "approved_on": now_datetime()})
	create_timesheet_for_approved_trip(trip)
	return "Approved"


def create_timesheet_for_approved_trip(trip):
	"""Source doc, Transport Timesheet: "Once the trip is approved by the
	operations in-charge, the timesheet for each project's trips should
	automatically generate."

	The trip is already Approved by the time this runs, so nothing here may undo
	that: a failure to build the timesheet is logged and reported, never raised."""
	from transport.transport.doctype.transport_timesheet.transport_timesheet import ensure_draft_timesheet

	try:
		result = ensure_draft_timesheet(trip)
	except Exception:
		frappe.log_error(title="Auto timesheet failed for Trip " + trip.name, message=frappe.get_traceback())
		frappe.msgprint(
			_("Trip approved, but its Timesheet could not be built automatically. Open a Transport "
			  "Timesheet for {0} and pull the trips in by hand.").format(trip.project),
			indicator="orange",
			alert=True,
		)
		return None

	if result and result.get("created"):
		from transport.transport.driver_portal import notify_roles

		notify_roles(
			("Transport Operations", "Transport In-Charge"),
			_("Draft Timesheet created - {0}").format(trip.project),
			_("Approving Trip {0} started a Draft Transport Timesheet ({1}) for {2}. Check it, then send it for approval.").format(
				trip.name, result["name"], trip.project
			),
			"Transport Timesheet",
			result["name"],
		)
	return result


@frappe.whitelist()
def start_trip(trip_name, start_odometer=None):
	"""Start a trip from the office, for a driver who is not using the portal.

	The driver's own start (driver_portal.start_trip) demands a vehicle photo
	and checks the phone's position against the pickup geofence. Neither is
	available to somebody at a desk, and requiring them would make this unusable
	for the case it exists for - a driver who phones in, or who has no portal
	account. What survives is everything that does not depend on being there:
	who is allowed to do this, and whether the trip is in a state where starting
	it means anything.

	Those two checks are the whole point. This replaces a Server Script that ran
	the same action through `safe_exec` with no role check at all, so any user
	who could reach the endpoint could start any trip in the system. It also
	could not be read, reviewed or deployed with the app, and it broke on an
	ordinary `.format()` call because `format` is a blocked attribute inside
	`safe_exec` - a sandbox rule that has nothing to do with starting trips.

	`db_set` rather than `save`, matching the driver path. Trip.validate clears
	`actual_start_time` for every status before Started (Trip.clear_unstarted_
	actuals, which exists because Frappe fills blank Time fields with the
	current time), so saving would wipe the stamp being set here.
	"""
	if not any(role in frappe.get_roles() for role in APPROVER_ROLES):
		frappe.throw(_("Not permitted to start trips."), frappe.PermissionError)

	trip = frappe.get_doc("Trip", trip_name)
	if trip.status not in STARTABLE_STATUSES:
		frappe.throw(
			_("Only an Assigned or Accepted trip can be started (current status: {0}).").format(
				trip.status
			)
		)

	trip.db_set({
		"status": "Started",
		"actual_start_time": nowtime(),
		"start_odometer": start_odometer,
	})
	return "Started"


@frappe.whitelist()
def end_trip(trip_name, end_odometer=None, driver_remarks=None):
	"""End a trip from the office, for a driver who is not using the portal.

	The counterpart to `start_trip` above, and the same trade: the driver's own
	end (driver_portal.end_trip) requires a photo of the drop location, which
	nobody at a desk can supply. Everything that does not need you to be there
	is kept, including the two steps that happen after the stamps are written.

	**`recalculate_after_actuals` is the reason this belongs in the app at all.**
	Duration and Duty/OT are derived from the actual times, and `db_set` skips
	`validate()`, so without it the trip keeps the duration it was *planned*
	with and hour-based OT is never applied to the leg that just finished. The
	Server Script this replaces could not do it: the function is not whitelisted
	so `frappe.call()` cannot reach it, and calling `doc.set_duration()` from
	inside `safe_exec` fails with "Not allowed to write to object", because a
	script may read a Document but never mutate one. A trip ended through that
	script was therefore costed on planned hours while one ended in the portal
	was costed on real ones - the same trip worth different money depending on
	which button finished it.
	"""
	if not any(role in frappe.get_roles() for role in APPROVER_ROLES):
		frappe.throw(_("Not permitted to end trips."), frappe.PermissionError)

	trip = frappe.get_doc("Trip", trip_name)
	if trip.status != "Started":
		frappe.throw(
			_("Only a Started trip can be ended (current status: {0}).").format(trip.status)
		)

	if end_odometer not in (None, ""):
		end_odometer = flt(end_odometer)
		# `is not None`, not a truth test: a start odometer of 0 is falsy, so a
		# plain `if trip.start_odometer` skips the check on every vehicle that
		# began the day on a fresh meter - and accepts a reading below it.
		if trip.start_odometer is not None and end_odometer < flt(trip.start_odometer):
			frappe.throw(
				_("End odometer ({0}) cannot be less than the start odometer ({1}).").format(
					end_odometer, flt(trip.start_odometer)
				)
			)
	else:
		end_odometer = None

	trip.db_set({
		"status": "Completed",
		"actual_end_time": nowtime(),
		"end_odometer": end_odometer,
		"driver_remarks": driver_remarks,
	})

	from transport.transport.driver_portal import check_fatigue, notify_roles
	from transport.transport.doctype.trip.trip import recalculate_after_actuals

	notify_roles(
		("Transport In-Charge",),
		_("Trip {0} finished - approval needed").format(trip.name),
		_("{0} ended Trip {1} from the office. Approve it to include in the timesheet.").format(
			frappe.session.user, trip.name
		),
		trip.doctype,
		trip.name,
	)
	recalculate_after_actuals(trip.name)
	check_fatigue(trip.driver, trip.trip_date)
	return "Completed"


# --------------------------------------------------------------------------
# Reallocation, bulk assignment and vehicle suggestion
# --------------------------------------------------------------------------

# Once a leg has started, who is driving it is history, not a plan - so only a
# trip that has not begun can be given a different driver or vehicle.
REALLOCATABLE_STATUSES = ("Draft", "Assigned", "Accepted", "Rejected")


def _require_office(action):
	if not any(role in frappe.get_roles() for role in APPROVER_ROLES):
		frappe.throw(_("Not permitted to {0}.").format(action), frappe.PermissionError)


def _assign(trip, driver=None, vehicle=None, reason=None):
	"""Give `trip` a different driver and/or vehicle. Saves through validate(),
	so the double-booking and blacklist checks apply exactly as they do when
	someone edits the form. Returns what changed."""
	if trip.status not in REALLOCATABLE_STATUSES:
		frappe.throw(
			_("Trip {0} is {1}; only a trip that has not started can be reallocated.").format(
				trip.name, trip.status
			)
		)

	before = (trip.driver, trip.vehicle)
	if driver:
		trip.driver = driver
	if vehicle:
		trip.vehicle = vehicle

	if (trip.driver, trip.vehicle) == before:
		return None

	# A new allocation is a fresh offer to the driver: the old acceptance or
	# rejection no longer applies, and the confirmation clock restarts.
	if trip.driver and trip.vehicle:
		trip.status = "Assigned"
		trip.assigned_on = now_datetime()
		trip.reminder_sent = 0
	trip.needs_reallocation = 0
	trip.rejection_reason = None
	trip.save()

	trip.add_comment(
		"Info",
		_("Reallocated by {0}. Driver: {1} to {2}. Vehicle: {3} to {4}.{5}").format(
			frappe.session.user,
			before[0] or _("none"), trip.driver or _("none"),
			before[1] or _("none"), trip.vehicle or _("none"),
			(" " + _("Reason: {0}").format(reason)) if reason else "",
		),
	)

	from transport.transport.driver_portal import notify_driver

	if before[0] and before[0] != trip.driver:
		notify_driver(
			before[0],
			_("Trip {0} reallocated").format(trip.name),
			_("You are no longer assigned to {0}.").format(trip.trip_title or trip.name),
			trip.doctype,
			trip.name,
		)
	if trip.driver and (trip.driver != before[0] or trip.vehicle != before[1]):
		notify_driver(
			trip.driver,
			_("Trip assigned: {0}").format(trip.trip_title or trip.name),
			_("{0} on {1}, vehicle {2}.").format(trip.trip_title or trip.name, trip.trip_date, trip.vehicle or "-"),
			trip.doctype,
			trip.name,
		)

	return {"driver": (before[0], trip.driver), "vehicle": (before[1], trip.vehicle)}


@frappe.whitelist()
def reallocate_trip(trip_name, driver=None, vehicle=None, reason=None):
	"""Change the driver and/or vehicle of a trip that is already allocated.

	The client's UAT question: once a driver and vehicle are allocated, "maybe
	sometimes change the driver or vehicle, in that case how to do". This is how:
	it re-runs the same checks as editing the form, restarts the driver's
	confirmation, tells both drivers, and leaves a comment saying who changed
	what and why - the Trip's version history keeps the before and after."""
	_require_office(_("reallocate trips"))
	if not (driver or vehicle):
		frappe.throw(_("Choose a new driver, a new vehicle, or both."))
	if not (reason or "").strip():
		frappe.throw(_("Say why the trip is being reallocated."))

	trip = frappe.get_doc("Trip", trip_name)
	changed = _assign(trip, driver or None, vehicle or None, reason.strip())
	if not changed:
		frappe.throw(_("That is already the driver and vehicle on this trip."))
	return changed


@frappe.whitelist()
def bulk_assign(trip_names, driver=None, vehicle=None):
	"""Give several trips the same driver and/or vehicle in one go - the
	"Assign driver" / "Assign vehicle" quick actions on the Trip list. A trip
	that cannot take it (already booked, blacklisted driver, already started)
	is reported and skipped; it never blocks the rest."""
	_require_office(_("assign trips"))
	if not (driver or vehicle):
		frappe.throw(_("Choose a driver, a vehicle, or both."))

	done, failed = [], []
	for name in frappe.parse_json(trip_names):
		frappe.db.savepoint("bulk_assign")
		try:
			trip = frappe.get_doc("Trip", name)
			_assign(trip, driver or None, vehicle or None, _("Bulk assignment"))
			done.append(name)
		except (frappe.ValidationError, frappe.PermissionError) as exc:
			frappe.db.rollback(save_point="bulk_assign")
			failed.append({"trip": name, "error": frappe.utils.strip_html(str(exc))})

	return {"done": done, "failed": failed}


@frappe.whitelist()
def suggest_vehicles(trip_date, scheduled_time=None, no_of_passengers=None, limit=10):
	"""Vehicles that could take a trip, best first.

	The client wants "vehicle availability and suggestion". A vehicle is offered
	when it is Available and not already on a trip at that date and time, and
	has enough seats if the passenger count is known. They are ranked by: no
	expired Mulkiya or insurance (an expired one is shown last, flagged), then
	the company's own vehicles before an outside supplier's (cheaper), then the
	tightest fit for the passengers, then the lightest day. The reasons are
	returned so the person choosing can see why."""
	frappe.has_permission("Trip", "read", throw=True)

	pax = frappe.utils.cint(no_of_passengers)

	busy = frappe._dict()
	for row in frappe.get_all(
		"Trip",
		filters={"trip_date": trip_date, "status": ("not in", ["Rejected", "Cancelled"]), "vehicle": ("is", "set")},
		fields=["vehicle", "scheduled_time"],
	):
		busy.setdefault(row.vehicle, []).append(row.scheduled_time)

	expired = set(
		frappe.get_all(
			"Compliance Document",
			filters={
				"attached_to_doctype": "Rental Vehicle",
				"status": "Expired",
				"document_type": ("in", ("Mulkiya (Registration)", "Insurance Policy")),
			},
			pluck="attached_to_name",
		)
	)

	requested = frappe.utils.to_timedelta(scheduled_time) if scheduled_time else None
	suggestions = []
	for v in frappe.get_all(
		"Rental Vehicle",
		filters={"status": "Available"},
		fields=["name", "vehicle_make", "vehicle_model", "vehicle_class", "seating_capacity",
				"ownership_type", "assigned_driver"],
	):
		times = busy.get(v.name, [])
		if requested is not None and requested in times:
			continue

		seats = frappe.utils.cint(v.seating_capacity)
		if pax and seats and seats < pax:
			continue

		reasons = []
		if seats:
			reasons.append(_("{0} seats").format(seats) + (_(" for {0} passengers").format(pax) if pax else ""))
		elif pax:
			reasons.append(_("seating not recorded"))
		reasons.append(_("company vehicle") if v.ownership_type == "Company-Owned" else
					   (_("outside supplier") if v.ownership_type else _("ownership not recorded")))
		reasons.append(_("{0} other trip(s) that day").format(len(times)) if times else _("free that day"))
		if v.name in expired:
			reasons.append(_("EXPIRED Mulkiya or insurance"))

		suggestions.append(
			{
				"vehicle": v.name,
				"label": " ".join(filter(None, [v.vehicle_make, v.vehicle_model])),
				"seating_capacity": v.seating_capacity,
				"vehicle_class": v.vehicle_class,
				"assigned_driver": v.assigned_driver,
				"reasons": ", ".join(reasons),
				"compliance_issue": v.name in expired,
				"_rank": (
					v.name in expired,
					# With a passenger count to meet, a vehicle whose seating is not
					# on record cannot be vouched for, so it ranks after every
					# vehicle that is known to fit.
					bool(pax) and not seats,
					v.ownership_type != "Company-Owned",
					(seats - pax) if (pax and seats) else 0,
					len(times),
				),
			}
		)

	suggestions.sort(key=lambda s: s["_rank"])
	for s in suggestions:
		del s["_rank"]
	return suggestions[: frappe.utils.cint(limit) or 10]
