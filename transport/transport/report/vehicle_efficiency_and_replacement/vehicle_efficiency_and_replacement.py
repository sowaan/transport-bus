# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

"""How hard each vehicle works and what it costs to keep running - the client's usage
efficiency, maintenance-versus-idle, high-fuel-consumption and "suggest vehicle
replacement based on cost trend" reports in one place.

Per vehicle over the period: trips, kilometres (from trip odometers), days used and
idle, fuel litres and cost, service cost, fines and tolls, running cost per
kilometre and kilometres per litre.

The **Suggestion** column is rule-based and says which rule fired, so it can be
argued with:

* Review for replacement - running cost over the last 90 days is at least 25% above
  the 90 days before, or cost per kilometre is at least 1.5 times the fleet median.
* High fuel use - litres per 100 km is at least 1.3 times the fleet median.
* Under-used - used on under 20% of the days in a period of 30 days or more.

The medians need at least three vehicles with data; with fewer, those two rules stay
silent rather than compare a vehicle to itself."""

import statistics

import frappe
from frappe import _
from frappe.utils import add_days, add_months, date_diff, flt, getdate, nowdate

TREND_THRESHOLD_PCT = 25
COST_PER_KM_FACTOR = 1.5
FUEL_FACTOR = 1.3
UNDER_USED_PCT = 20
MIN_VEHICLES_FOR_MEDIAN = 3


def execute(filters=None):
	filters = frappe._dict(filters or {})
	to_date = getdate(filters.get("to_date") or nowdate())
	from_date = getdate(filters.get("from_date") or add_months(to_date, -6))
	return get_columns(), get_data(filters, from_date, to_date)


def get_columns():
	return [
		{"label": _("Vehicle"), "fieldname": "vehicle", "fieldtype": "Link", "options": "Rental Vehicle", "width": 120},
		{"label": _("Model"), "fieldname": "model", "fieldtype": "Data", "width": 130},
		{"label": _("Year"), "fieldname": "year", "fieldtype": "Int", "width": 55},
		{"label": _("Ownership"), "fieldname": "ownership_type", "fieldtype": "Data", "width": 110},
		{"label": _("Trips"), "fieldname": "trips", "fieldtype": "Int", "width": 55},
		{"label": _("KM"), "fieldname": "km", "fieldtype": "Float", "precision": 0, "width": 70},
		{"label": _("Days Used"), "fieldname": "days_used", "fieldtype": "Int", "width": 75},
		{"label": _("Idle Days"), "fieldname": "idle_days", "fieldtype": "Int", "width": 75},
		{"label": _("Used %"), "fieldname": "used_pct", "fieldtype": "Percent", "width": 70},
		{"label": _("Fuel (L)"), "fieldname": "litres", "fieldtype": "Float", "precision": 0, "width": 75},
		{"label": _("KM per Litre"), "fieldname": "km_per_litre", "fieldtype": "Float", "precision": 1, "width": 85},
		{"label": _("Fuel Cost"), "fieldname": "fuel_cost", "fieldtype": "Currency", "width": 95},
		{"label": _("Service Cost"), "fieldname": "service_cost", "fieldtype": "Currency", "width": 95},
		{"label": _("Fines"), "fieldname": "fines", "fieldtype": "Currency", "width": 85},
		{"label": _("Tolls"), "fieldname": "tolls", "fieldtype": "Currency", "width": 80},
		{"label": _("Running Cost"), "fieldname": "running_cost", "fieldtype": "Currency", "width": 105},
		{"label": _("Cost per KM"), "fieldname": "cost_per_km", "fieldtype": "Currency", "precision": 2, "width": 90},
		{"label": _("Cost vs Prior 90d %"), "fieldname": "trend_pct", "fieldtype": "Percent", "width": 125},
		{"label": _("Suggestion"), "fieldname": "suggestion", "fieldtype": "Data", "width": 210},
	]


def by_vehicle(sql, values):
	return {r.vehicle: r for r in frappe.db.sql(sql, values, as_dict=True)}


def get_data(filters, from_date, to_date):
	span = {"from_date": from_date, "to_date": to_date}
	days = date_diff(to_date, from_date) + 1

	vehicle_conditions, vvalues = ["1=1"], {}
	for fieldname in ("ownership_type", "company"):
		if filters.get(fieldname):
			vehicle_conditions.append(f"rv.{fieldname} = %({fieldname})s")
			vvalues[fieldname] = filters[fieldname]
	vehicles = frappe.db.sql(
		f"""select rv.name as vehicle, trim(concat_ws(' ', rv.vehicle_make, rv.vehicle_model)) as model,
			rv.year, rv.ownership_type from `tabRental Vehicle` rv where {' and '.join(vehicle_conditions)} order by rv.name""",
		vvalues,
		as_dict=True,
	)

	trips = by_vehicle(
		"""select t.vehicle, count(*) as trips, count(distinct t.trip_date) as days_used,
			sum(if(t.start_odometer is not null and t.end_odometer is not null and t.end_odometer >= t.start_odometer,
				t.end_odometer - t.start_odometer, 0)) as km
		   from `tabTrip` t where t.status in ('Completed', 'Approved') and t.vehicle is not null
			and t.trip_date between %(from_date)s and %(to_date)s group by t.vehicle""",
		span,
	)
	fuel = by_vehicle(
		"""select f.vehicle, ifnull(sum(f.volume), 0) as litres, ifnull(sum(f.total_cost), 0) as cost
		   from `tabFuel History` f where f.date >= %(from_date)s and f.date < date_add(%(to_date)s, interval 1 day)
		   group by f.vehicle""",
		span,
	)
	service = by_vehicle(
		"""select s.vehicle, ifnull(sum(s.total_cost), 0) as cost from `tabService History` s
		   where s.service_date between %(from_date)s and %(to_date)s group by s.vehicle""",
		span,
	)
	fines = by_vehicle(
		"""select s.vehicle, ifnull(sum(s.total_cost), 0) as cost from `tabTraffic Fine Staging` s
		   where s.status != 'Cancelled' and s.vehicle is not null
			and s.fine_datetime >= %(from_date)s and s.fine_datetime < date_add(%(to_date)s, interval 1 day) group by s.vehicle""",
		span,
	)
	tolls = by_vehicle(
		"""select c.vehicle, ifnull(sum(c.amount), 0) as cost from `tabToll Crossing` c
		   where c.vehicle is not null and c.crossed_on >= %(from_date)s
			and c.crossed_on < date_add(%(to_date)s, interval 1 day) group by c.vehicle""",
		span,
	)

	# Fuel and service only, in the two 90-day windows ending on the period's last day:
	# the trend is about what it costs to keep the vehicle running, and fines and
	# tolls are not the vehicle's wear.
	recent_start, prior_start = add_days(to_date, -89), add_days(to_date, -179)
	windows = {"recent_from": recent_start, "prior_from": prior_start, "to_date": to_date, "prior_to": add_days(recent_start, -1)}
	window_cost = by_vehicle(
		"""select v.vehicle,
			sum(if(v.on_date >= %(recent_from)s, v.cost, 0)) as recent,
			sum(if(v.on_date < %(recent_from)s, v.cost, 0)) as prior
		   from (
			select vehicle, date(date) as on_date, ifnull(total_cost, 0) as cost from `tabFuel History`
			union all
			select vehicle, service_date as on_date, ifnull(total_cost, 0) as cost from `tabService History`
		   ) v where v.on_date between %(prior_from)s and %(to_date)s group by v.vehicle""",
		windows,
	)

	rows = []
	for v in vehicles:
		t, f, s = trips.get(v.vehicle), fuel.get(v.vehicle), service.get(v.vehicle)
		row = frappe._dict(v)
		row.trips = t.trips if t else 0
		row.km = flt(t.km) if t else 0
		row.days_used = t.days_used if t else 0
		row.idle_days = max(days - row.days_used, 0)
		row.used_pct = row.days_used / days * 100 if days else 0
		row.litres = flt(f.litres) if f else 0
		row.fuel_cost = flt(f.cost) if f else 0
		row.service_cost = flt(s.cost) if s else 0
		row.fines = flt(fines[v.vehicle].cost) if v.vehicle in fines else 0
		row.tolls = flt(tolls[v.vehicle].cost) if v.vehicle in tolls else 0
		row.running_cost = row.fuel_cost + row.service_cost + row.fines + row.tolls
		row.km_per_litre = row.km / row.litres if (row.km and row.litres) else None
		row.cost_per_km = row.running_cost / row.km if row.km else None

		w = window_cost.get(v.vehicle)
		row.trend_pct = ((flt(w.recent) - flt(w.prior)) / flt(w.prior) * 100) if (w and flt(w.prior) > 0) else None
		row._recent = flt(w.recent) if w else 0
		rows.append(row)

	cost_per_km = [r.cost_per_km for r in rows if r.cost_per_km]
	litres_per_100 = [100 / r.km_per_litre for r in rows if r.km_per_litre]
	median_cpk = statistics.median(cost_per_km) if len(cost_per_km) >= MIN_VEHICLES_FOR_MEDIAN else None
	median_l100 = statistics.median(litres_per_100) if len(litres_per_100) >= MIN_VEHICLES_FOR_MEDIAN else None

	for r in rows:
		reasons = []
		if r.trend_pct is not None and r.trend_pct >= TREND_THRESHOLD_PCT and r._recent > 0:
			reasons.append(_("Review for replacement: cost up {0}% on the prior 90 days").format(round(r.trend_pct)))
		elif median_cpk and r.cost_per_km and r.cost_per_km >= COST_PER_KM_FACTOR * median_cpk:
			reasons.append(_("Review for replacement: cost per km {0}x the fleet median").format(round(r.cost_per_km / median_cpk, 1)))
		if median_l100 and r.km_per_litre and (100 / r.km_per_litre) >= FUEL_FACTOR * median_l100:
			reasons.append(_("High fuel use"))
		if days >= 30 and r.used_pct < UNDER_USED_PCT:
			reasons.append(_("Under-used"))
		r.suggestion = "; ".join(reasons)
		del r["_recent"]

	if filters.get("only_flagged"):
		rows = [r for r in rows if r.suggestion]
	return rows
