# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

"""The client's "Company Vehicle List", column for column: vehicle number, type,
registered company, Mulkiya and insurance expiry, model, vehicle value, the three
renewal fees and their total, insurance, remarks and MBL number. The fee, insurance
and MBL columns come from the fields added to the vehicle master for this list."""

import frappe
from frappe import _
from frappe.utils import add_days, getdate, nowdate


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{"label": _("SL #"), "fieldname": "sl_no", "fieldtype": "Int", "width": 50},
		{"label": _("Vehicle Number"), "fieldname": "vehicle", "fieldtype": "Link", "options": "Rental Vehicle", "width": 130},
		{"label": _("Vehicle Type"), "fieldname": "vehicle_type", "fieldtype": "Data", "width": 110},
		{"label": _("Register Company"), "fieldname": "company", "fieldtype": "Link", "options": "Company", "width": 200},
		{"label": _("Mulkiya Exp"), "fieldname": "registration_expiry", "fieldtype": "Date", "width": 100},
		{"label": _("Insurance Exp"), "fieldname": "insurance_expiry", "fieldtype": "Date", "width": 100},
		{"label": _("Model"), "fieldname": "model", "fieldtype": "Data", "width": 140},
		{"label": _("Vehicle Value"), "fieldname": "vehicle_cost", "fieldtype": "Currency", "width": 110},
		{"label": _("Mulkiya Renewal Fee"), "fieldname": "mulkiya_renewal_fee", "fieldtype": "Currency", "width": 110},
		{"label": _("Insurance Renewal Fee"), "fieldname": "insurance_renewal_fee", "fieldtype": "Currency", "width": 110},
		{"label": _("Passing Fee & Commission & Certificate"), "fieldname": "passing_fee", "fieldtype": "Currency", "width": 130},
		{"label": _("Total Renewal Fee"), "fieldname": "total_renewal_fee", "fieldtype": "Currency", "width": 110},
		{"label": _("Insurance"), "fieldname": "insurance_provider", "fieldtype": "Data", "width": 130},
		{"label": _("Remarks"), "fieldname": "vehicle_remarks", "fieldtype": "Data", "width": 160},
		{"label": _("MBL Number"), "fieldname": "mbl_number", "fieldtype": "Data", "width": 110},
	]


def get_data(filters):
	conditions, values = ["1=1"], {}
	for fieldname in ("company", "ownership_type", "vehicle_type"):
		if filters.get(fieldname):
			conditions.append(f"rv.{fieldname} = %({fieldname})s")
			values[fieldname] = filters[fieldname]

	if filters.get("expiring_in_days") not in (None, ""):
		# Includes anything already expired: the point is "needs attention by then".
		conditions.append(
			"(rv.registration_expiry <= %(horizon)s or rv.insurance_expiry <= %(horizon)s)"
		)
		values["horizon"] = add_days(getdate(nowdate()), int(filters.expiring_in_days))

	rows = frappe.db.sql(
		f"""
		select rv.name as vehicle, rv.vehicle_type, rv.company, rv.registration_expiry, rv.insurance_expiry,
			trim(concat_ws(' ', rv.vehicle_make, rv.vehicle_model)) as model, rv.vehicle_cost,
			rv.mulkiya_renewal_fee, rv.insurance_renewal_fee, rv.passing_fee, rv.total_renewal_fee,
			rv.insurance_provider, rv.vehicle_remarks, rv.mbl_number
		from `tabRental Vehicle` rv
		where {" and ".join(conditions)}
		order by rv.company, rv.name
		""",
		values,
		as_dict=True,
	)
	for index, row in enumerate(rows, start=1):
		row["sl_no"] = index
	return rows
