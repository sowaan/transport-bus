# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

"""A month of daily vehicle inspections laid out as the client's paper sheet: the 17
check points down the side, days 1 to 31 across, each cell the first letter of the
condition - G (Good), F (Fair), P (Poor) - and a remarks column on the right."""

import calendar

import frappe
from frappe import _
from frappe.utils import cint, getdate

from transport.transport.doctype.vehicle_inspection.vehicle_inspection import CHECK_POINTS

MONTHS = [calendar.month_name[i] for i in range(1, 13)]
LETTER = {"Good": "G", "Fair": "F", "Poor": "P"}


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.get("vehicle"):
		return get_columns(), [], _("Choose a vehicle.")

	year = cint(filters.get("year")) or getdate().year
	month = MONTHS.index(filters.month) + 1 if filters.get("month") in MONTHS else getdate().month
	last_day = calendar.monthrange(year, month)[1]
	start, end = f"{year}-{month:02d}-01", f"{year}-{month:02d}-{last_day:02d}"

	rows = frappe.db.sql(
		"""
		select p.inspection_date, c.sl_no, c.condition, c.remarks
		from `tabVehicle Inspection` p
		join `tabVehicle Inspection Check Point` c on c.parent = p.name and c.parenttype = 'Vehicle Inspection'
		where p.vehicle = %s and p.inspection_type = 'Daily' and p.docstatus < 2
			and p.inspection_date between %s and %s
		""",
		(filters.vehicle, start, end),
		as_dict=True,
	)
	done_days = {
		d.day for d in frappe.get_all(
			"Vehicle Inspection",
			filters={"vehicle": filters.vehicle, "inspection_type": "Daily", "inspection_date": ("between", [start, end])},
			pluck="inspection_date",
		)
	}

	by_point = {}
	for r in rows:
		by_point.setdefault(r.sl_no, []).append(r)

	data = []
	header = {"sl_no": "", "check_point": _("Inspection recorded")}
	for day in range(1, 32):
		header[f"d{day}"] = "✔" if day in done_days else ""
	data.append(header)

	poor = 0
	for index, (point, frequency) in enumerate(CHECK_POINTS, start=1):
		row = {"sl_no": index, "check_point": f"{point}  ({frequency})"}
		notes = []
		for entry in by_point.get(index, []):
			letter = LETTER.get(entry.condition, "")
			row[f"d{entry.inspection_date.day}"] = letter
			poor += letter == "P"
			if entry.remarks:
				notes.append(f"{entry.inspection_date.day}: {entry.remarks}")
		row["remarks"] = "; ".join(notes)
		data.append(row)

	message = _("{0} - {1} {2}: {3} day(s) inspected, {4} point(s) marked Poor.").format(
		filters.vehicle, MONTHS[month - 1], year, len(done_days), poor
	)
	return get_columns(), data, message


def get_columns():
	columns = [
		{"label": _("Sl."), "fieldname": "sl_no", "fieldtype": "Data", "width": 45},
		{"label": _("Check Points"), "fieldname": "check_point", "fieldtype": "Data", "width": 330},
	]
	columns += [{"label": str(day), "fieldname": f"d{day}", "fieldtype": "Data", "width": 38} for day in range(1, 32)]
	columns.append({"label": _("Remarks"), "fieldname": "remarks", "fieldtype": "Data", "width": 220})
	return columns
