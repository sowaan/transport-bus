// Copyright (c) 2026, Sowaan and contributors
// For license information, please see license.txt

frappe.query_reports["Toll Expense Report"] = {
	filters: [
		{ fieldname: "authority", label: __("Authority"), fieldtype: "Select", options: ["", "Salik", "Darb"] },
		{ fieldname: "from_date", label: __("From"), fieldtype: "Date", default: frappe.datetime.month_start() },
		{ fieldname: "to_date", label: __("To"), fieldtype: "Date", default: frappe.datetime.month_end() },
		{ fieldname: "project", label: __("Project"), fieldtype: "Link", options: "Project" },
		{ fieldname: "vehicle", label: __("Vehicle"), fieldtype: "Link", options: "Rental Vehicle" },
		{ fieldname: "matched", label: __("Matched to a Trip"), fieldtype: "Select", options: ["", "Matched", "Unmatched"] },
	],
};
