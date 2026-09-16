# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

"""Doc section 17 (Vehicle Management & Reports): Fuel usage, Maintenance
cost, Fine report, rolled into one vehicle-level cost view. Reuses
fleetify's Fuel History / Service History (the shared Rental Vehicle
master) plus this app's own Traffic Fine Staging - deliberately does not
attempt a per-project cost split (see Project Profit and Loss's note on
why shared-vehicle costs aren't allocated per project)."""

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
	filters = frappe._dict(filters or {})

	if filters.get("vehicle"):
		vehicle_filters = {"name": filters.vehicle}
	else:
		vehicle_filters = {"name": ("in", frappe.get_all("Trip", pluck="vehicle", distinct=True))}

	vehicles = frappe.get_all(
		"Rental Vehicle", filters=vehicle_filters, fields=["name", "vehicle_make", "vehicle_model"]
	)

	data = []
	for vehicle in vehicles:
		fuel_cost = get_sum("Fuel History", "vehicle", vehicle.name, "date", filters, "total_cost")
		maintenance_cost = get_sum("Service History", "vehicle", vehicle.name, "service_date", filters, "total_cost")
		# Every fetched fine now counts, not just the handful someone had promoted
		# into a separate doctype. Cancelled rows are excluded because they are not
		# a cost; Unpaid ones are included because they are a liability already
		# incurred. `total_cost` carries VAT when a row has it switched on.
		fine_cost = get_sum(
			"Traffic Fine Staging", "vehicle", vehicle.name, "fine_datetime", filters, "total_cost",
			extra={"status": ("!=", "Cancelled")},
		)

		data.append(
			{
				"vehicle": vehicle.name,
				"vehicle_make": vehicle.vehicle_make,
				"vehicle_model": vehicle.vehicle_model,
				"fuel_cost": fuel_cost,
				"maintenance_cost": maintenance_cost,
				"fine_cost": fine_cost,
				"total_cost": fuel_cost + maintenance_cost + fine_cost,
			}
		)

	return get_columns(), data


def get_sum(doctype, link_field, vehicle, date_field, filters, sum_field, extra=None):
	conditions = {link_field: vehicle}
	if extra:
		conditions.update(extra)
	if filters.get("from_date") and filters.get("to_date"):
		conditions[date_field] = ("between", [filters.from_date, filters.to_date])

	return flt(frappe.db.get_value(doctype, conditions, f"sum({sum_field})") or 0)


def get_columns():
	return [
		{"label": _("Vehicle"), "fieldname": "vehicle", "fieldtype": "Link", "options": "Rental Vehicle", "width": 120},
		{"label": _("Make"), "fieldname": "vehicle_make", "fieldtype": "Data", "width": 100},
		{"label": _("Model"), "fieldname": "vehicle_model", "fieldtype": "Data", "width": 100},
		{"label": _("Fuel Cost"), "fieldname": "fuel_cost", "fieldtype": "Currency", "width": 110},
		{"label": _("Maintenance Cost"), "fieldname": "maintenance_cost", "fieldtype": "Currency", "width": 130},
		{"label": _("Fine Cost"), "fieldname": "fine_cost", "fieldtype": "Currency", "width": 110},
		{"label": _("Total Cost"), "fieldname": "total_cost", "fieldtype": "Currency", "width": 120},
	]
