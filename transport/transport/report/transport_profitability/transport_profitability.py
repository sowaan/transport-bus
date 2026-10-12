# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

"""Profit and loss by vehicle, driver, trip, project or outsourced vehicle - the
client's "Profit & Loss reports based on vehicle, driver, trip, outsourced vehicle",
with loss-making and profit-making trips picked out.

**How revenue is attributed** - this is a policy, and it is the thing to challenge:

* A Sales Invoice raised from a Transport Timesheet has its **net total** (VAT
  excluded) divided equally among that timesheet's trips. A trip's revenue is its
  share. A trip not yet on an invoiced timesheet has none, and is flagged.
* An invoice raised for a *Monthly per Vehicle* timesheet is billed by the vehicle-
  month, not the trip. Under the Vehicle and Outsourced groupings its net total is
  divided equally among the vehicles on its deployments; under Trip, Driver and
  Project it is divided among whatever trips the timesheet lists. Either way it is
  counted once.

**Costs counted** - what can be tied to a trip: approved and booked Trip Expenses, and
Salik / Darb crossings matched to the trip. For the Vehicle and Outsourced groupings
the vehicle's fuel, services and fines in the period are added, and its monthly
EMI / supplier price (from the vehicle master) for the months in the period.

**Not counted:** driver salary (the client has not yet defined the payroll basis) and
anything not recorded against a trip or vehicle. Treat profit here as contribution,
not as the company's accounts.

Fuel appears both as a Trip Expense (a driver's receipt) and in Fuel History (a
fleet fuel card). If both are kept for the same fuel, the Vehicle grouping counts it
twice; the Fuel & Service column is separate so it can be read without it."""

import frappe
from frappe import _
from frappe.utils import add_months, date_diff, flt, getdate, nowdate

DAYS_PER_MONTH = 30.4
GROUPS = ("Vehicle", "Driver", "Trip", "Project", "Outsourced Vehicle")


def execute(filters=None):
	filters = frappe._dict(filters or {})
	to_date = getdate(filters.get("to_date") or nowdate())
	from_date = getdate(filters.get("from_date") or add_months(to_date, -1))
	group = filters.get("group_by") or "Vehicle"
	return get_columns(group), get_data(filters, group, from_date, to_date)


def get_columns(group):
	label = {"Vehicle": _("Vehicle"), "Driver": _("Driver"), "Trip": _("Trip"),
			 "Project": _("Project"), "Outsourced Vehicle": _("Outsourced Vehicle")}[group]
	link = {"Vehicle": "Rental Vehicle", "Outsourced Vehicle": "Rental Vehicle", "Driver": "Driver", "Trip": "Trip", "Project": "Project"}[group]
	return [
		{"label": label, "fieldname": "key", "fieldtype": "Link", "options": link, "width": 150},
		{"label": _("Name"), "fieldname": "label", "fieldtype": "Data", "width": 200},
		{"label": _("Trips"), "fieldname": "trips", "fieldtype": "Int", "width": 60},
		{"label": _("Revenue"), "fieldname": "revenue", "fieldtype": "Currency", "width": 105},
		{"label": _("Trip Expenses"), "fieldname": "trip_expenses", "fieldtype": "Currency", "width": 105},
		{"label": _("Tolls"), "fieldname": "tolls", "fieldtype": "Currency", "width": 85},
		{"label": _("Fuel & Service"), "fieldname": "fuel_service", "fieldtype": "Currency", "width": 105},
		{"label": _("Fines"), "fieldname": "fines", "fieldtype": "Currency", "width": 85},
		{"label": _("Vehicle Fixed Cost"), "fieldname": "fixed", "fieldtype": "Currency", "width": 115},
		{"label": _("Total Cost"), "fieldname": "cost", "fieldtype": "Currency", "width": 105},
		{"label": _("Profit"), "fieldname": "profit", "fieldtype": "Currency", "width": 105},
		{"label": _("Margin %"), "fieldname": "margin", "fieldtype": "Percent", "width": 85},
		{"label": _("Result"), "fieldname": "result", "fieldtype": "Data", "width": 110},
	]


def get_data(filters, group, from_date, to_date):
	months = (date_diff(to_date, from_date) + 1) / DAYS_PER_MONTH
	span = {"from_date": from_date, "to_date": to_date}

	conditions = ["t.status in ('Completed', 'Approved')", "t.trip_date between %(from_date)s and %(to_date)s"]
	for fieldname in ("project", "vehicle", "driver"):
		if filters.get(fieldname):
			conditions.append(f"t.{fieldname} = %({fieldname})s")
			span[fieldname] = filters[fieldname]

	trips = frappe.db.sql(
		f"""select t.name, t.trip_title, t.project, t.vehicle, t.driver, d.full_name as driver_name, t.timesheet,
			rv.ownership_type
		   from `tabTrip` t left join `tabDriver` d on d.name = t.driver
		   left join `tabRental Vehicle` rv on rv.name = t.vehicle
		   where {' and '.join(conditions)}""",
		span,
		as_dict=True,
	)
	trip_names = [t.name for t in trips]

	def sums(sql):
		if not trip_names:
			return {}
		return {r.k: flt(r.v) for r in frappe.db.sql(sql, {"trips": trip_names}, as_dict=True)}

	expenses = sums(
		"""select trip as k, sum(amount) as v from `tabTrip Expense`
		   where trip in %(trips)s and status in ('Approved', 'Booked') group by trip""")
	tolls = sums("""select trip as k, sum(amount) as v from `tabToll Crossing` where trip in %(trips)s group by trip""")

	# Revenue: each invoiced timesheet's net total, split across its trips.
	revenue, monthly_timesheets = {}, set()
	timesheets = {t.timesheet for t in trips if t.timesheet}
	if timesheets:
		for ts in frappe.db.sql(
			"""select ts.name, ts.billing_basis, si.net_total,
				(select count(*) from `tabTransport Timesheet Trip` c where c.parent = ts.name) as n
			   from `tabTransport Timesheet` ts join `tabSales Invoice` si on si.name = ts.sales_invoice
			   where ts.name in %(ts)s and si.docstatus = 1""",
			{"ts": list(timesheets)},
			as_dict=True,
		):
			revenue[ts.name] = flt(ts.net_total) / ts.n if ts.n else 0
			if ts.billing_basis == "Monthly per Vehicle":
				monthly_timesheets.add(ts.name)

	by_vehicle = group in ("Vehicle", "Outsourced Vehicle")

	rows = {}

	def bucket(key, label, ownership=None):
		return rows.setdefault(key, frappe._dict(key=key, label=label, trips=0, revenue=0, trip_expenses=0, tolls=0,
			fuel_service=0, fines=0, fixed=0, not_invoiced=0, ownership=ownership))

	def keyed(t):
		if group == "Trip":
			return t.name, t.trip_title
		if group == "Driver":
			return t.driver, t.driver_name
		if group == "Project":
			return t.project, frappe.db.get_value("Project", t.project, "project_name") if t.project else None
		if group == "Outsourced Vehicle" and t.ownership_type != "External Supplier":
			return None, None
		return t.vehicle, t.vehicle

	for t in trips:
		key, label = keyed(t)
		if not key:
			continue
		b = bucket(key, label, t.ownership_type)
		b.trips += 1
		# A monthly-per-vehicle invoice is added per vehicle below, not per trip.
		if not (by_vehicle and t.timesheet in monthly_timesheets):
			b.revenue += revenue.get(t.timesheet, 0)
		b.trip_expenses += expenses.get(t.name, 0)
		b.tolls += tolls.get(t.name, 0)
		b.not_invoiced += 0 if t.timesheet in revenue else 1

	if by_vehicle:
		# Monthly-per-vehicle revenue, which is billed by the vehicle rather than the trip.
		for ts in frappe.db.sql(
			"""select ts.name, si.net_total from `tabTransport Timesheet` ts join `tabSales Invoice` si on si.name = ts.sales_invoice
			   where ts.billing_basis = 'Monthly per Vehicle' and si.docstatus = 1
				and ts.period_to >= %(from_date)s and ts.period_from <= %(to_date)s""",
			span,
			as_dict=True,
		):
			vehicles = frappe.get_all("Transport Vehicle Deployment", filters={"parent": ts.name}, pluck="vehicle")
			for vehicle in vehicles:
				ownership = frappe.db.get_value("Rental Vehicle", vehicle, "ownership_type")
				if group == "Outsourced Vehicle" and ownership != "External Supplier":
					continue
				bucket(vehicle, vehicle, ownership).revenue += flt(ts.net_total) / len(vehicles)

		for vehicle, b in rows.items():
			fuel = frappe.db.sql("select ifnull(sum(total_cost), 0) from `tabFuel History` where vehicle = %s and date >= %s and date < date_add(%s, interval 1 day)",
				(vehicle, span["from_date"], span["to_date"]))[0][0]
			service = frappe.db.sql("select ifnull(sum(total_cost), 0) from `tabService History` where vehicle = %s and service_date between %s and %s",
				(vehicle, span["from_date"], span["to_date"]))[0][0]
			fines = frappe.db.sql("select ifnull(sum(total_cost), 0) from `tabTraffic Fine Staging` where vehicle = %s and status != 'Cancelled' and fine_datetime >= %s and fine_datetime < date_add(%s, interval 1 day)",
				(vehicle, span["from_date"], span["to_date"]))[0][0]
			monthly = flt(frappe.db.get_value("Rental Vehicle", vehicle, "monthly_emi_or_supplier_price"))
			b.fuel_service, b.fines, b.fixed = flt(fuel) + flt(service), flt(fines), monthly * months

	out = []
	for b in rows.values():
		b.cost = b.trip_expenses + b.tolls + b.fuel_service + b.fines + b.fixed
		b.profit = b.revenue - b.cost
		b.margin = (b.profit / b.revenue * 100) if b.revenue else None
		if b.profit < 0:
			b.result = "Loss"
		elif b.revenue == 0 and b.not_invoiced:
			b.result = "Not invoiced"
		else:
			b.result = "Profit"
		out.append(b)

	if filters.get("result"):
		out = [b for b in out if b.result == filters.result]
	out.sort(key=lambda b: b.profit)
	return out
