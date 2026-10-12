# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

"""Everything that has happened to one vehicle, newest first - the client's "vehicle
all log history report". Trips, fuel, services, inspections, fines, tolls, document
expiries and registration renewals, each a line that links to its record."""

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.get("vehicle"):
		return get_columns(), [], _("Choose a vehicle.")
	return get_columns(), get_events(filters)


def get_columns():
	return [
		{"label": _("When"), "fieldname": "when", "fieldtype": "Datetime", "width": 150},
		{"label": _("Event"), "fieldname": "event", "fieldtype": "Data", "width": 90},
		{"label": _("Record"), "fieldname": "reference", "fieldtype": "Dynamic Link", "options": "ref_doctype", "width": 160},
		{"label": _("Details"), "fieldname": "details", "fieldtype": "Data", "width": 330},
		{"label": _("Driver"), "fieldname": "driver_name", "fieldtype": "Data", "width": 130},
		{"label": _("KM / Litres"), "fieldname": "quantity", "fieldtype": "Data", "width": 100},
		{"label": _("Amount"), "fieldname": "amount", "fieldtype": "Currency", "width": 95},
		{"label": "", "fieldname": "ref_doctype", "fieldtype": "Data", "hidden": 1, "width": 0},
	]


def date_range(column, filters, values):
	clause = ""
	if filters.get("from_date"):
		clause += f" and {column} >= %(from_date)s"
		values["from_date"] = filters.from_date
	if filters.get("to_date"):
		clause += f" and {column} < date_add(%(to_date)s, interval 1 day)"
		values["to_date"] = filters.to_date
	return clause


def get_events(filters):
	values = {"vehicle": filters.vehicle}
	events = []

	def add(rows, event, doctype):
		for r in rows:
			r["event"], r["ref_doctype"] = event, doctype
			events.append(r)

	add(frappe.db.sql(
		f"""select concat(t.trip_date, ' ', ifnull(t.scheduled_time, '00:00:00')) as `when`, t.name as reference,
			concat(t.from_place, ' to ', t.to_place, ' (', t.direction, ', ', t.status, ')') as details,
			d.full_name as driver_name,
			if(t.end_odometer is not null and t.start_odometer is not null and t.end_odometer >= t.start_odometer,
				concat(round(t.end_odometer - t.start_odometer, 1), ' km'), '') as quantity, 0 as amount
		from `tabTrip` t left join `tabDriver` d on d.name = t.driver
		where t.vehicle = %(vehicle)s and t.status not in ('Draft', 'Cancelled') {date_range('t.trip_date', filters, values)}""",
		values, as_dict=True), _("Trip"), "Trip")

	add(frappe.db.sql(
		f"""select f.date as `when`, f.name as reference,
			concat('Fuel at meter ', ifnull(f.meter_entry, '?')) as details, '' as driver_name,
			concat(ifnull(f.volume, 0), ' L') as quantity, f.total_cost as amount
		from `tabFuel History` f where f.vehicle = %(vehicle)s {date_range('f.date', filters, values)}""",
		values, as_dict=True), _("Fuel"), "Fuel History")

	add(frappe.db.sql(
		f"""select s.service_date as `when`, s.name as reference,
			concat(ifnull(s.service_task, 'Service'), if(s.next_service_date is not null, concat(' (next ', s.next_service_date, ')'), '')) as details,
			'' as driver_name, concat(ifnull(s.current_mileage, 0), ' km') as quantity, s.total_cost as amount
		from `tabService History` s where s.vehicle = %(vehicle)s {date_range('s.service_date', filters, values)}""",
		values, as_dict=True), _("Service"), "Service History")

	add(frappe.db.sql(
		f"""select i.inspection_date as `when`, i.name as reference,
			concat(i.inspection_type, ' inspection',
				ifnull(concat(' - ', (select group_concat(c.check_point separator ', ') from `tabVehicle Inspection Check Point` c
					where c.parent = i.name and c.condition = 'Poor')), '')) as details,
			i.driver_name as driver_name, if(i.odometer_reading, concat(i.odometer_reading, ' km'), '') as quantity, 0 as amount
		from `tabVehicle Inspection` i where i.vehicle = %(vehicle)s {date_range('i.inspection_date', filters, values)}""",
		values, as_dict=True), _("Inspection"), "Vehicle Inspection")

	add(frappe.db.sql(
		f"""select s.fine_datetime as `when`, s.name as reference,
			concat_ws(' - ', s.fine_type, s.fine_location, s.ticket_number) as details, d.full_name as driver_name,
			'' as quantity, s.total_cost as amount
		from `tabTraffic Fine Staging` s left join `tabDriver` d on d.name = s.driver
		where s.vehicle = %(vehicle)s and s.status != 'Cancelled' {date_range('s.fine_datetime', filters, values)}""",
		values, as_dict=True), _("Fine"), "Traffic Fine Staging")

	add(frappe.db.sql(
		f"""select c.crossed_on as `when`, c.name as reference, concat(c.authority, ' - ', ifnull(c.gate, '')) as details,
			'' as driver_name, '' as quantity, c.amount as amount
		from `tabToll Crossing` c where c.vehicle = %(vehicle)s {date_range('c.crossed_on', filters, values)}""",
		values, as_dict=True), _("Toll"), "Toll Crossing")

	add(frappe.db.sql(
		f"""select cd.expiry_date as `when`, cd.name as reference,
			concat(cd.document_type, ' expires', ifnull(concat(' (', cd.document_number, ')'), '')) as details,
			'' as driver_name, '' as quantity, 0 as amount
		from `tabCompliance Document` cd
		where cd.attached_to_doctype = 'Rental Vehicle' and cd.attached_to_name = %(vehicle)s {date_range('cd.expiry_date', filters, values)}""",
		values, as_dict=True), _("Document"), "Compliance Document")

	add(frappe.db.sql(
		f"""select vr.creation as `when`, vr.name as reference,
			concat('Registration renewal - ', vr.status, ' (', ifnull(vr.current_stage, ''), ')') as details,
			'' as driver_name, '' as quantity, vr.total_cost as amount
		from `tabVehicle Renewal` vr where vr.vehicle = %(vehicle)s {date_range('vr.creation', filters, values)}""",
		values, as_dict=True), _("Renewal"), "Vehicle Renewal")

	events.sort(key=lambda e: str(e["when"]), reverse=True)
	return events
