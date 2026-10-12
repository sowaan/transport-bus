// Copyright (c) 2026, Sowaan and contributors
// For license information, please see license.txt

frappe.query_reports["Transport Request Statement"] = {
	filters: [
		{ fieldname: "customer", label: __("Requesting Company"), fieldtype: "Link", options: "Customer" },
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.month_start(),
		},
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", default: frappe.datetime.month_end() },
		{ fieldname: "status", label: __("Status"), fieldtype: "Select", options: ["", "Open", "Invoiced"] },
	],
};
