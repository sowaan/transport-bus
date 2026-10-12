// Copyright (c) 2026, Sowaan and contributors
// For license information, please see license.txt

frappe.query_reports["Vehicle Monthly KM Log"] = {
	filters: [
		{ fieldname: "vehicle", label: __("Vehicle"), fieldtype: "Link", options: "Rental Vehicle" },
		{ fieldname: "from_date", label: __("From"), fieldtype: "Date", default: frappe.datetime.add_months(frappe.datetime.get_today(), -6) },
		{ fieldname: "to_date", label: __("To"), fieldtype: "Date", default: frappe.datetime.get_today() },
	],
};
