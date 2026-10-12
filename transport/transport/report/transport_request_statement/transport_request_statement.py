# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

"""The client's month-end request sheet: one line per request - date, pick up,
drop off, times, vehicle, driver, KM, rate - totalled per company. This is what
backs the single invoice line, and the "Intercompany transportation requests"
report the client asked for."""

import frappe
from frappe import _


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{"label": _("Date"), "fieldname": "request_date", "fieldtype": "Date", "width": 95},
		{"label": _("Requesting Company"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 170},
		{"label": _("Pick Up"), "fieldname": "pickup_location", "fieldtype": "Data", "width": 140},
		{"label": _("Drop Off"), "fieldname": "drop_location", "fieldtype": "Data", "width": 140},
		{"label": _("From"), "fieldname": "start_time", "fieldtype": "Time", "width": 80},
		{"label": _("To"), "fieldname": "end_time", "fieldtype": "Time", "width": 80},
		{"label": _("Vehicle"), "fieldname": "vehicle", "fieldtype": "Link", "options": "Rental Vehicle", "width": 100},
		{"label": _("Driver"), "fieldname": "driver_name", "fieldtype": "Data", "width": 120},
		{"label": _("KM"), "fieldname": "km", "fieldtype": "Float", "width": 60},
		{"label": _("Rate"), "fieldname": "charge", "fieldtype": "Currency", "width": 90},
		{"label": _("Requested By"), "fieldname": "requested_by", "fieldtype": "Data", "width": 120},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 80},
		{"label": _("Invoice"), "fieldname": "sales_invoice", "fieldtype": "Link", "options": "Sales Invoice", "width": 130},
	]


def get_data(filters):
	conditions, values = ["r.status != 'Cancelled'"], {}
	if filters.get("customer"):
		conditions.append("r.customer = %(customer)s")
		values["customer"] = filters.customer
	if filters.get("status"):
		conditions.append("r.status = %(status)s")
		values["status"] = filters.status
	if filters.get("from_date"):
		conditions.append("r.request_date >= %(from_date)s")
		values["from_date"] = filters.from_date
	if filters.get("to_date"):
		conditions.append("r.request_date <= %(to_date)s")
		values["to_date"] = filters.to_date

	rows = frappe.db.sql(
		f"""
		select r.request_date, r.customer, r.pickup_location, r.drop_location,
			time(r.start_time) as start_time, time(r.end_time) as end_time,
			r.vehicle, d.full_name as driver_name, r.km, r.charge, r.requested_by,
			r.status, r.sales_invoice
		from `tabTransport Request` r
		left join `tabDriver` d on d.name = r.driver
		where {" and ".join(conditions)}
		order by r.customer, r.request_date, r.creation
		""",
		values,
		as_dict=True,
	)
	return rows
