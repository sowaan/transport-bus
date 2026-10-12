# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

"""Salik and Darb crossings, by vehicle, trip and project - the "toll expenses"
the client wants tracked. Amounts are the toll portal's own, **including VAT**."""

import frappe
from frappe import _


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{"label": _("Crossed On"), "fieldname": "crossed_on", "fieldtype": "Datetime", "width": 150},
		{"label": _("Authority"), "fieldname": "authority", "fieldtype": "Data", "width": 70},
		{"label": _("Plate"), "fieldname": "plate_text", "fieldtype": "Data", "width": 120},
		{"label": _("Vehicle"), "fieldname": "vehicle", "fieldtype": "Link", "options": "Rental Vehicle", "width": 110},
		{"label": _("Gate"), "fieldname": "gate", "fieldtype": "Data", "width": 150},
		{"label": _("Trip"), "fieldname": "trip", "fieldtype": "Link", "options": "Trip", "width": 140},
		{"label": _("Project"), "fieldname": "project", "fieldtype": "Link", "options": "Project", "width": 110},
		{"label": _("Matched By"), "fieldname": "match_basis", "fieldtype": "Data", "width": 130},
		{"label": _("Amount (incl. VAT)"), "fieldname": "amount", "fieldtype": "Currency", "width": 120},
	]


def get_data(filters):
	conditions, values = ["1=1"], {}
	for fieldname in ("authority", "vehicle", "project"):
		if filters.get(fieldname):
			conditions.append(f"tc.{fieldname} = %({fieldname})s")
			values[fieldname] = filters[fieldname]
	if filters.get("from_date"):
		conditions.append("tc.crossed_on >= %(from_date)s")
		values["from_date"] = filters.from_date
	if filters.get("to_date"):
		conditions.append("tc.crossed_on < date_add(%(to_date)s, interval 1 day)")
		values["to_date"] = filters.to_date
	if filters.get("matched") == "Matched":
		conditions.append("ifnull(tc.trip, '') != ''")
	elif filters.get("matched") == "Unmatched":
		conditions.append("ifnull(tc.trip, '') = ''")

	return frappe.db.sql(
		f"""
		select tc.crossed_on, tc.authority, tc.plate_text, tc.vehicle, tc.gate, tc.trip,
			tc.project, tc.match_basis, tc.amount
		from `tabToll Crossing` tc
		where {" and ".join(conditions)}
		order by tc.crossed_on desc
		""",
		values,
		as_dict=True,
	)
