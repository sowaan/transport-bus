# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

"""Project by project: the kilometres the quotation assumed against the kilometres
the vehicles actually ran, and the fuel spent doing it - the client's "Expected KM vs
fuel consumed, project-wise".

Expected kilometres come from the project's **latest** Rate Calculation: each vehicle
line's estimated monthly kilometres times its quantity, scaled to the length of the
period. Actual kilometres come from trip odometers (a trip without both readings adds
nothing, so a project with patchy readings under-reports). Fuel spend is the approved
and booked Fuel expenses against the project's trips; the project's monthly fuel limit
is scaled the same way."""

import frappe
from frappe import _
from frappe.utils import add_months, date_diff, flt, getdate, nowdate

DAYS_PER_MONTH = 30.4
KM_TOLERANCE_PCT = 10


def execute(filters=None):
	filters = frappe._dict(filters or {})
	to_date = getdate(filters.get("to_date") or nowdate())
	from_date = getdate(filters.get("from_date") or add_months(to_date, -1))
	return get_columns(), get_data(filters, from_date, to_date)


def get_columns():
	return [
		{"label": _("Project"), "fieldname": "project", "fieldtype": "Link", "options": "Project", "width": 130},
		{"label": _("Customer"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 170},
		{"label": _("Expected KM"), "fieldname": "expected_km", "fieldtype": "Float", "precision": 0, "width": 100},
		{"label": _("Actual KM"), "fieldname": "actual_km", "fieldtype": "Float", "precision": 0, "width": 100},
		{"label": _("Variance KM"), "fieldname": "variance_km", "fieldtype": "Float", "precision": 0, "width": 100},
		{"label": _("Variance %"), "fieldname": "variance_pct", "fieldtype": "Percent", "width": 90},
		{"label": _("Fuel Spend"), "fieldname": "fuel_spend", "fieldtype": "Currency", "width": 100},
		{"label": _("Fuel per KM"), "fieldname": "fuel_per_km", "fieldtype": "Currency", "precision": 2, "width": 95},
		{"label": _("Fuel Limit"), "fieldname": "fuel_limit", "fieldtype": "Currency", "width": 100},
		{"label": _("Fuel % of Limit"), "fieldname": "fuel_limit_pct", "fieldtype": "Percent", "width": 110},
		{"label": _("Flag"), "fieldname": "flag", "fieldtype": "Data", "width": 220},
	]


def get_data(filters, from_date, to_date):
	scale = (date_diff(to_date, from_date) + 1) / DAYS_PER_MONTH
	values = {"from_date": from_date, "to_date": to_date}

	actual = {
		r.project: r
		for r in frappe.db.sql(
			"""select t.project,
				sum(if(t.start_odometer is not null and t.end_odometer is not null and t.end_odometer >= t.start_odometer,
					t.end_odometer - t.start_odometer, 0)) as km
			   from `tabTrip` t where t.status in ('Completed', 'Approved')
				and t.trip_date between %(from_date)s and %(to_date)s group by t.project""",
			values,
			as_dict=True,
		)
	}
	fuel = {
		r.project: flt(r.spend)
		for r in frappe.db.sql(
			"""select e.project, sum(e.amount) as spend from `tabTrip Expense` e
			   where e.expense_type = 'Fuel' and e.status in ('Approved', 'Booked')
				and e.expense_date between %(from_date)s and %(to_date)s group by e.project""",
			values,
			as_dict=True,
		)
	}

	projects = set(actual) | set(fuel)
	if filters.get("project"):
		projects &= {filters.project}

	rows = []
	for project in sorted(p for p in projects if p):
		info = frappe.db.get_value(
			"Project", project, ["customer", "transport_monthly_fuel_limit"], as_dict=True
		) or frappe._dict()

		calc = frappe.db.get_value(
			"Transport Rate Calculation", {"project": project}, "name", order_by="creation desc"
		)
		monthly_km = 0
		if calc:
			monthly_km = sum(
				flt(r.estimated_km) * (r.qty or 1)
				for r in frappe.get_all(
					"Transport Rate Calculation Vehicle",
					filters={"parent": calc, "parenttype": "Transport Rate Calculation"},
					fields=["estimated_km", "qty"],
				)
			)

		row = frappe._dict(project=project, customer=info.customer)
		row.expected_km = monthly_km * scale if monthly_km else None
		row.actual_km = flt(actual[project].km) if project in actual else 0
		row.variance_km = (row.actual_km - row.expected_km) if row.expected_km else None
		row.variance_pct = (row.variance_km / row.expected_km * 100) if row.expected_km else None
		row.fuel_spend = fuel.get(project, 0)
		row.fuel_per_km = row.fuel_spend / row.actual_km if row.actual_km else None
		row.fuel_limit = flt(info.transport_monthly_fuel_limit) * scale if flt(info.transport_monthly_fuel_limit) else None
		row.fuel_limit_pct = (row.fuel_spend / row.fuel_limit * 100) if row.fuel_limit else None

		flags = []
		if row.variance_pct is not None and row.variance_pct > KM_TOLERANCE_PCT:
			flags.append(_("Ran {0}% over expected km").format(round(row.variance_pct)))
		elif row.variance_pct is not None and row.variance_pct < -KM_TOLERANCE_PCT:
			flags.append(_("Ran {0}% under expected km").format(round(-row.variance_pct)))
		if row.fuel_limit_pct is not None and row.fuel_limit_pct >= 100:
			flags.append(_("Fuel over limit"))
		if not calc:
			flags.append(_("No Rate Calculation to compare with"))
		row.flag = "; ".join(flags)
		rows.append(row)

	return rows
