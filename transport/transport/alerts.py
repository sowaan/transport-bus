# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

"""Daily reminders: document expiry, and customer PO expiry / consumption.

Each job sends **one digest per recipient**, not one message per document. A
fleet has hundreds of dated documents, and the first run on a site that has
never had these alerts would otherwise send one message for every document
already expired.
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, cstr, flt, getdate, nowdate

from transport.transport.compliance_sync import sync_all_expiry_sources
from transport.transport.driver_portal import _notify_users, notify_roles

ALERT_ROLES = ("Transport Operations", "Transport In-Charge", "Transport Accounts")
PO_ROLES = ("Transport Accounts", "Transport Operations")

DEFAULT_EXPIRY_DAYS = (30, 15, 7)
DEFAULT_ASATEEL_DAYS = (15,)
ASATEEL_TYPE = "Asateel Permit"


def parse_days(text, fallback):
	"""'30, 15, 7' -> [30, 15, 7]; anything unusable falls back to the default."""
	days = {int(part) for part in cstr(text or "").replace(";", ",").split(",") if part.strip().isdigit()}
	return sorted(days or fallback, reverse=True)


def band_for(days_left, thresholds):
	"""The tightest day-mark a document has reached, or None if it has reached
	none. Zero is always a mark: the day it expires, and every day after, is the
	"expired" band, so an expired document is reported once, not daily."""
	reached = [mark for mark in sorted(set(thresholds) | {0}) if days_left <= mark]
	return reached[0] if reached else None


def _link(doctype, name, label=None):
	route = frappe.scrub(doctype).replace("_", "-")
	return f'<a href="/app/{route}/{frappe.utils.escape_html(name)}">{frappe.utils.escape_html(label or name)}</a>'


def _table(headers, rows):
	head = "".join(f"<th style='text-align:left;padding:2px 10px'>{frappe.utils.escape_html(h)}</th>" for h in headers)
	body = "".join(
		"<tr>" + "".join(f"<td style='padding:2px 10px'>{cell}</td>" for cell in row) + "</tr>" for row in rows
	)
	return f"<table><tr>{head}</tr>{body}</table>"


def _holder_label(doctype, name):
	if doctype == "Employee":
		return frappe.db.get_value("Employee", name, "employee_name") or name
	if doctype == "Driver":
		return frappe.db.get_value("Driver", name, "full_name") or name
	return name


# ---------------------------------------------------------------- expiry alerts


def send_expiry_alerts():
	"""Compliance Document reminders at one month, 15 days and one week (set in
	Transport Settings), and once more when the date passes - until the date is
	updated, at which point the cycle starts again for the new date."""
	sync_all_expiry_sources()

	standard = parse_days(
		frappe.db.get_single_value("Transport Settings", "expiry_alert_days"), DEFAULT_EXPIRY_DAYS
	)
	asateel = parse_days(
		frappe.db.get_single_value("Transport Settings", "asateel_permit_alert_days"), DEFAULT_ASATEEL_DAYS
	)
	today = getdate(nowdate())

	due = []
	for row in frappe.get_all(
		"Compliance Document",
		fields=[
			"name", "attached_to_doctype", "attached_to_name", "document_type", "expiry_date",
			"last_alerted_threshold", "last_alerted_for_expiry",
		],
	):
		days_left = (getdate(row.expiry_date) - today).days
		band = band_for(days_left, asateel if row.document_type == ASATEEL_TYPE else standard)
		if band is None:
			continue

		# Already told about this expiry date at this mark, or at a tighter one.
		# Gated on the date because the Int column cannot say "never alerted":
		# Frappe stores an unset Int as 0, which is also a real mark.
		same_expiry = row.last_alerted_for_expiry and getdate(row.last_alerted_for_expiry) == getdate(row.expiry_date)
		if same_expiry and cint(row.last_alerted_threshold) <= band:
			continue

		row.days_left, row.band = days_left, band
		due.append(row)

	if not due:
		return 0

	due.sort(key=lambda r: r.days_left)
	rows = []
	for r in due:
		when = _("expired {0} day(s) ago").format(-r.days_left) if r.days_left < 0 else (
			_("expires today") if r.days_left == 0 else _("in {0} day(s)").format(r.days_left)
		)
		rows.append([
			_link("Compliance Document", r.name, r.document_type),
			frappe.utils.escape_html(f"{r.attached_to_doctype}: {_holder_label(r.attached_to_doctype, r.attached_to_name)}"),
			frappe.utils.formatdate(r.expiry_date),
			frappe.utils.escape_html(when),
		])

	notify_roles(
		ALERT_ROLES,
		_("Expiry reminders - {0} document(s)").format(len(due)),
		_table([_("Document"), _("Held by"), _("Expiry"), _("When")], rows),
	)

	for r in due:
		frappe.db.set_value(
			"Compliance Document",
			r.name,
			{"last_alerted_threshold": r.band, "last_alerted_for_expiry": r.expiry_date},
			update_modified=False,
		)

	return len(due)


# -------------------------------------------------------------------- PO alerts

OPEN_ORDER = ("not in", ("Closed", "Completed", "Cancelled"))


def send_po_alerts():
	"""Customer PO expiry, and PO consumption, on transport Sales Orders.

	Scoped to orders that carry a transport project: Sales Order is shared with
	the group's other companies, whose customers' POs are not this team's
	business. "Consumed" is the share of the order already invoiced
	(`per_billed`), since the PO and the Sales Order are the same commitment."""
	window = cint(frappe.db.get_single_value("Transport Settings", "po_expiry_alert_days")) or 30
	percent = cint(frappe.db.get_single_value("Transport Settings", "po_consumed_alert_percent")) or 80
	today = getdate(nowdate())

	base = {"docstatus": 1, "transport_project": ("is", "set"), "status": OPEN_ORDER}
	fields = ["name", "customer", "po_no", "owner", "per_billed", "grand_total", "currency",
			  "transport_customer_po_expiry", "transport_po_expiry_alerted_for"]

	# `is set` as well as `<=`: Frappe wraps a date comparison in ifnull(.., '0001-01-01'),
	# so without it every order with no PO date would count as long expired.
	expiring = [
		o for o in frappe.get_all(
			"Sales Order",
			filters=[
				*[[k, "=" if not isinstance(v, tuple) else v[0], v if not isinstance(v, tuple) else v[1]]
				  for k, v in base.items()],
				["transport_customer_po_expiry", "is", "set"],
				["transport_customer_po_expiry", "<=", add_days(today, window)],
			],
			fields=fields,
		)
		if not o.transport_po_expiry_alerted_for
		or getdate(o.transport_po_expiry_alerted_for) != getdate(o.transport_customer_po_expiry)
	]
	consumed = frappe.get_all(
		"Sales Order",
		filters={**base, "per_billed": (">=", percent), "transport_po_consumed_alerted": 0},
		fields=fields,
	)

	if expiring:
		rows = []
		for o in sorted(expiring, key=lambda o: o.transport_customer_po_expiry):
			days_left = (getdate(o.transport_customer_po_expiry) - today).days
			rows.append([
				_link("Sales Order", o.name),
				frappe.utils.escape_html(o.customer or ""),
				frappe.utils.escape_html(o.po_no or ""),
				frappe.utils.formatdate(o.transport_customer_po_expiry),
				_("expired") if days_left < 0 else _("{0} day(s) left").format(days_left),
			])
		_send_po_digest(
			_("Customer PO expiring - {0} order(s)").format(len(expiring)),
			_table([_("Sales Order"), _("Customer"), _("PO No."), _("PO Expires"), _("Left")], rows),
			expiring,
		)
		for o in expiring:
			frappe.db.set_value(
				"Sales Order", o.name, "transport_po_expiry_alerted_for", o.transport_customer_po_expiry,
				update_modified=False,
			)

	if consumed:
		rows = [[
			_link("Sales Order", o.name),
			frappe.utils.escape_html(o.customer or ""),
			frappe.utils.escape_html(o.po_no or ""),
			f"{flt(o.per_billed):.0f}%",
		] for o in consumed]
		_send_po_digest(
			_("Customer PO {0}% consumed - {1} order(s)").format(percent, len(consumed)),
			_table([_("Sales Order"), _("Customer"), _("PO No."), _("Invoiced")], rows),
			consumed,
		)
		for o in consumed:
			frappe.db.set_value("Sales Order", o.name, "transport_po_consumed_alerted", 1, update_modified=False)

	return len(expiring) + len(consumed)


def _send_po_digest(subject, message, orders):
	notify_roles(PO_ROLES, subject, message)

	# The salesperson who owns an order is told about their own, separately.
	by_owner = {}
	for o in orders:
		by_owner.setdefault(o.owner, []).append(o)
	for owner, owned in by_owner.items():
		if owner and owner != "Administrator":
			_notify_users([owner], subject, ", ".join(o.name for o in owned), "Sales Order", owned[0].name)


# ------------------------------------------------------------ service reminders


def send_service_reminders():
	"""Email Operations and Accounts when a vehicle's next service is coming due.

	Reads Service History, which already records what was done (`service_task` -
	oil filter, tyres, monthly check-up) and when the next one is due
	(`next_service_date`, `next_service_mileage`). Only each vehicle's **latest**
	service counts: an older record's "next service" was superseded the day the
	later one was entered. A service is reminded once; recording the next service
	starts a new cycle.

	So the reminder is exactly as good as the due date entered on the last
	Service History - staff need to fill that in."""
	# fleetify's Service History arrived in the same release as Fuel History and
	# Place; a site on an older fleetify has none of them, and has nothing to remind.
	if not frappe.db.table_exists("Service History") or not frappe.db.has_column("Service History", "transport_reminder_sent"):
		return 0

	lead = cint(frappe.db.get_single_value("Transport Settings", "service_reminder_days")) or 7
	today = getdate(nowdate())

	latest = frappe.db.sql(
		"""
		select sh.name, sh.vehicle, sh.service_task, sh.next_service_date, sh.next_service_mileage
		from `tabService History` sh
		where sh.transport_reminder_sent = 0
		  and sh.service_date = (
			select max(s2.service_date) from `tabService History` s2 where s2.vehicle = sh.vehicle
		  )
		  and sh.name = (
			select s3.name from `tabService History` s3
			where s3.vehicle = sh.vehicle and s3.service_date = sh.service_date
			order by s3.creation desc limit 1
		  )
		""",
		as_dict=True,
	)

	due = []
	for row in latest:
		mileage = flt(frappe.db.get_value("Rental Vehicle", row.vehicle, "mileage"))
		by_date = row.next_service_date and getdate(row.next_service_date) <= add_days(today, lead)
		by_km = flt(row.next_service_mileage) and mileage and mileage >= flt(row.next_service_mileage)
		if by_date or by_km:
			row.mileage = mileage
			row.reason = _("date") if by_date else _("mileage")
			due.append(row)

	if not due:
		return 0

	rows = [
		[
			_link("Rental Vehicle", r.vehicle),
			frappe.utils.escape_html(r.service_task or ""),
			frappe.utils.formatdate(r.next_service_date) if r.next_service_date else "",
			f"{flt(r.next_service_mileage):,.0f}" if r.next_service_mileage else "",
			f"{r.mileage:,.0f}" if r.mileage else "",
		]
		for r in sorted(due, key=lambda r: r.next_service_date or add_days(today, 3650))
	]
	notify_roles(
		ALERT_ROLES,
		_("Service due - {0} vehicle(s)").format(len(due)),
		_table([_("Vehicle"), _("Last service task"), _("Next service date"), _("Next service at (km)"), _("Odometer (km)")], rows),
	)
	for r in due:
		frappe.db.set_value("Service History", r.name, "transport_reminder_sent", 1, update_modified=False)
	return len(due)


# ----------------------------------------------------------------- fuel limits


def send_fuel_limit_alerts():
	"""Tell Accounts and Operations when a month's fuel reaches a limit.

	Two limits, in the unit each source can honestly give:

	* a **vehicle**, in litres - from Fuel History, which records volume;
	* a **project**, in money - from approved Trip Expenses of type Fuel, which
	  record only an amount.

	Each is reported once per month (the month is stored on the record), so a
	vehicle sitting over its limit is not reported every morning."""
	month_start = frappe.utils.get_first_day(nowdate())
	month_key = month_start.strftime("%Y-%m")
	lines = []

	if frappe.db.table_exists("Fuel History") and frappe.db.has_column("Rental Vehicle", "monthly_fuel_limit_litres"):
		for v in frappe.get_all(
			"Rental Vehicle",
			filters=[["monthly_fuel_limit_litres", ">", 0], ["fuel_limit_alerted_month", "!=", month_key]],
			fields=["name", "monthly_fuel_limit_litres"],
		):
			used = flt(frappe.db.sql(
				"select sum(volume) from `tabFuel History` where vehicle = %s and date >= %s",
				(v.name, month_start),
			)[0][0])
			if used >= flt(v.monthly_fuel_limit_litres):
				lines.append([_link("Rental Vehicle", v.name), _("vehicle"), f"{used:,.0f} L", f"{flt(v.monthly_fuel_limit_litres):,.0f} L"])
				frappe.db.set_value("Rental Vehicle", v.name, "fuel_limit_alerted_month", month_key, update_modified=False)

	if frappe.db.has_column("Project", "transport_monthly_fuel_limit"):
		for p in frappe.get_all(
			"Project",
			filters=[["transport_monthly_fuel_limit", ">", 0], ["transport_fuel_limit_alerted_month", "!=", month_key]],
			fields=["name", "transport_monthly_fuel_limit"],
		):
			used = flt(frappe.db.sql(
				"""select sum(amount) from `tabTrip Expense`
				   where project = %s and expense_type = 'Fuel' and status in ('Approved', 'Booked')
				     and expense_date >= %s""",
				(p.name, month_start),
			)[0][0])
			if used >= flt(p.transport_monthly_fuel_limit):
				lines.append([_link("Project", p.name), _("project"), f"{used:,.2f}", f"{flt(p.transport_monthly_fuel_limit):,.2f}"])
				frappe.db.set_value("Project", p.name, "transport_fuel_limit_alerted_month", month_key, update_modified=False)

	if lines:
		notify_roles(
			("Transport Accounts", "Transport Operations"),
			_("Fuel limit reached - {0}").format(len(lines)),
			_table([_("For"), _("Is a"), _("Fuel this month"), _("Limit")], lines),
		)
	return len(lines)


# ------------------------------------------------------------ inspection reminders


def send_inspection_reminders():
	"""Tell Operations which vehicles are due their fortnightly inspection.

	The client has the Operations in-charge inspect every vehicle twice a month as
	it comes in. A vehicle is due when its last Fortnightly inspection is older than
	the interval in Transport Settings (15 days), or it has never had one. Each is
	reminded about at most once a week, so a vehicle that stays due is not reported
	every morning."""
	if not frappe.db.has_column("Rental Vehicle", "inspection_reminded_on"):
		return 0

	interval = cint(frappe.db.get_single_value("Transport Settings", "fortnightly_inspection_days")) or 15
	today = getdate(nowdate())
	cutoff = add_days(today, -interval)

	last = {
		r.vehicle: r.last_on
		for r in frappe.db.sql(
			"""select vehicle, max(inspection_date) as last_on from `tabVehicle Inspection`
			   where inspection_type = 'Fortnightly' group by vehicle""",
			as_dict=True,
		)
	}

	due = []
	for v in frappe.get_all(
		"Rental Vehicle",
		filters={"status": ("in", ["Available", "Rented"])},
		fields=["name", "inspection_reminded_on"],
	):
		last_on = last.get(v.name)
		if last_on and getdate(last_on) >= cutoff:
			continue
		if v.inspection_reminded_on and getdate(v.inspection_reminded_on) > add_days(today, -7):
			continue
		due.append((v.name, last_on))

	if not due:
		return 0

	rows = [
		[_link("Rental Vehicle", name), frappe.utils.formatdate(last_on) if last_on else _("never")]
		for name, last_on in sorted(due, key=lambda d: (d[1] is not None, str(d[1])))
	]
	notify_roles(
		("Transport Operations", "Transport In-Charge"),
		_("Inspection due - {0} vehicle(s)").format(len(due)),
		_table([_("Vehicle"), _("Last fortnightly inspection")], rows),
	)
	for name, _last in due:
		frappe.db.set_value("Rental Vehicle", name, "inspection_reminded_on", today, update_modified=False)
	return len(due)
