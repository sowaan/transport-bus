# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

"""Driver-wise traffic violations, fines and black-point history, with good and bad
drivers picked out - the client's "Blacklist / Incident History" report.

Two views:

* **Summary** - one row per driver: fines, their cost, black points, incidents,
  and a standing.
* **Fines & Incidents** - every fine and incident behind those numbers, newest first.

**Standing** is a plain rule, stated here so nobody has to guess at it:

* Blacklisted - the driver is blacklisted.
* Bad - black points are at or past half the blacklist threshold (Transport
  Settings, default 10), so one more serious offence may blacklist them.
* Watch - any black point, fine or incident in the period.
* Good - nothing in the period.

**Black points** are the driver's applied total (Driver.total_black_points). Points
carried by a fine that is on hold - not yet applied to the driver - are shown
separately, because they do not count toward blacklisting until released.

Fines with no driver recorded cannot be attributed to anyone and are left out;
they are the Traffic Fine Staging list's to resolve."""

import frappe
from frappe import _
from frappe.utils import flt

STANDING_ORDER = {"Blacklisted": 0, "Bad": 1, "Watch": 2, "Good": 3}


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if filters.get("view") == "Fines & Incidents":
		return detail_columns(), detail_data(filters)
	return summary_columns(), summary_data(filters)


def summary_columns():
	return [
		{"label": _("Driver"), "fieldname": "driver", "fieldtype": "Link", "options": "Driver", "width": 110},
		{"label": _("Name"), "fieldname": "driver_name", "fieldtype": "Data", "width": 160},
		{"label": _("Standing"), "fieldname": "standing", "fieldtype": "Data", "width": 90},
		{"label": _("Fines"), "fieldname": "fines", "fieldtype": "Int", "width": 60},
		{"label": _("Fines Cost"), "fieldname": "fines_cost", "fieldtype": "Currency", "width": 100},
		{"label": _("Unpaid Fines"), "fieldname": "unpaid_fines", "fieldtype": "Int", "width": 90},
		{"label": _("Black Points"), "fieldname": "black_points", "fieldtype": "Int", "width": 90},
		{"label": _("Points On Hold"), "fieldname": "points_on_hold", "fieldtype": "Int", "width": 100},
		{"label": _("Incidents"), "fieldname": "incidents", "fieldtype": "Int", "width": 80},
		{"label": _("Accidents"), "fieldname": "accidents", "fieldtype": "Int", "width": 80},
		{"label": _("Last Event"), "fieldname": "last_event", "fieldtype": "Date", "width": 95},
		{"label": _("Avg Rating"), "fieldname": "average_rating", "fieldtype": "Float", "precision": 1, "width": 85},
	]


def date_clause(column, filters, values, suffix):
	clause = []
	if filters.get("from_date"):
		clause.append(f"{column} >= %(from_date)s")
		values["from_date"] = filters.from_date
	if filters.get("to_date"):
		clause.append(f"{column} < date_add(%(to_date)s, interval 1 day)")
		values["to_date"] = filters.to_date
	return (" and " + " and ".join(clause)) if clause else ""


def summary_data(filters):
	values = {}
	fine_range = date_clause("s.fine_datetime", filters, values, "fine")
	incident_range = date_clause("i.incident_date", filters, values, "incident")

	threshold = frappe.utils.cint(frappe.db.get_single_value("Transport Settings", "blacklist_threshold_points")) or 10

	driver_filter = ""
	if filters.get("driver"):
		driver_filter = "and d.name = %(driver)s"
		values["driver"] = filters.driver

	rows = frappe.db.sql(
		f"""
		select d.name as driver, d.full_name as driver_name, d.total_black_points as black_points,
			d.is_blacklisted, d.average_rating,
			(select count(*) from `tabTraffic Fine Staging` s
				where s.driver = d.name and s.status != 'Cancelled' {fine_range}) as fines,
			(select ifnull(sum(s.total_cost), 0) from `tabTraffic Fine Staging` s
				where s.driver = d.name and s.status != 'Cancelled' {fine_range}) as fines_cost,
			(select count(*) from `tabTraffic Fine Staging` s
				where s.driver = d.name and s.status = 'Unpaid' {fine_range}) as unpaid_fines,
			(select ifnull(sum(s.black_points), 0) from `tabTraffic Fine Staging` s
				where s.driver = d.name and s.black_points_on_hold = 1 and s.status != 'Cancelled' {fine_range}) as points_on_hold,
			(select count(*) from `tabDriver Incident` i
				where i.driver = d.name {incident_range}) as incidents,
			(select count(*) from `tabDriver Incident` i
				where i.driver = d.name and i.incident_type = 'Accident' {incident_range}) as accidents,
			greatest(
				ifnull((select max(date(s.fine_datetime)) from `tabTraffic Fine Staging` s where s.driver = d.name {fine_range}), '1000-01-01'),
				ifnull((select max(i.incident_date) from `tabDriver Incident` i where i.driver = d.name {incident_range}), '1000-01-01')
			) as last_event
		from `tabDriver` d
		where 1=1 {driver_filter}
		order by d.full_name
		""",
		values,
		as_dict=True,
	)

	out = []
	for row in rows:
		row["black_points"] = frappe.utils.cint(row.black_points)
		row["points_on_hold"] = frappe.utils.cint(row.points_on_hold)
		if str(row.last_event) == "1000-01-01":
			row["last_event"] = None

		if row.is_blacklisted:
			standing = "Blacklisted"
		elif row.black_points * 2 >= threshold:
			standing = "Bad"
		elif row.black_points or row.fines or row.incidents:
			standing = "Watch"
		else:
			standing = "Good"
		row["standing"] = standing

		if filters.get("standing") and filters.standing != standing:
			continue
		if filters.get("only_with_history") and standing == "Good":
			continue
		out.append(row)

	out.sort(key=lambda r: (STANDING_ORDER[r.standing], -r.black_points, r.driver_name or ""))
	return out


def detail_columns():
	return [
		{"label": _("Date"), "fieldname": "event_date", "fieldtype": "Datetime", "width": 150},
		{"label": _("Driver"), "fieldname": "driver", "fieldtype": "Link", "options": "Driver", "width": 110},
		{"label": _("Name"), "fieldname": "driver_name", "fieldtype": "Data", "width": 150},
		{"label": _("Kind"), "fieldname": "kind", "fieldtype": "Data", "width": 80},
		{"label": _("Reference"), "fieldname": "reference", "fieldtype": "Dynamic Link", "options": "ref_doctype", "width": 150},
		{"label": _("Type"), "fieldname": "type", "fieldtype": "Data", "width": 170},
		{"label": _("Vehicle"), "fieldname": "vehicle", "fieldtype": "Data", "width": 100},
		{"label": _("Amount"), "fieldname": "amount", "fieldtype": "Currency", "width": 90},
		{"label": _("Black Points"), "fieldname": "points", "fieldtype": "Int", "width": 90},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 130},
		{"label": "", "fieldname": "ref_doctype", "fieldtype": "Data", "hidden": 1, "width": 0},
	]


def detail_data(filters):
	values = {}
	fine_range = date_clause("s.fine_datetime", filters, values, "fine")
	incident_range = date_clause("i.incident_date", filters, values, "incident")
	driver_filter_s = driver_filter_i = ""
	if filters.get("driver"):
		driver_filter_s = "and s.driver = %(driver)s"
		driver_filter_i = "and i.driver = %(driver)s"
		values["driver"] = filters.driver

	fines = frappe.db.sql(
		f"""
		select s.fine_datetime as event_date, s.driver, d.full_name as driver_name, 'Fine' as kind,
			s.name as reference, 'Traffic Fine Staging' as ref_doctype,
			concat_ws(' - ', s.fine_type, s.ticket_number) as type, s.plate as vehicle,
			s.total_cost as amount, s.black_points as points,
			concat(s.status, if(s.black_points_on_hold = 1, ' (points on hold)', '')) as status
		from `tabTraffic Fine Staging` s join `tabDriver` d on d.name = s.driver
		where s.status != 'Cancelled' {fine_range} {driver_filter_s}
		""",
		values,
		as_dict=True,
	)
	incidents = frappe.db.sql(
		f"""
		select i.incident_date as event_date, i.driver, d.full_name as driver_name, 'Incident' as kind,
			i.name as reference, 'Driver Incident' as ref_doctype, i.incident_type as type, '' as vehicle,
			0 as amount, i.black_points as points, i.status as status
		from `tabDriver Incident` i join `tabDriver` d on d.name = i.driver
		where 1=1 {incident_range} {driver_filter_i}
		""",
		values,
		as_dict=True,
	)
	rows = fines + incidents
	rows.sort(key=lambda r: str(r.event_date), reverse=True)
	return rows
