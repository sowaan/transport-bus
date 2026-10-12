// Copyright (c) 2026, Sowaan and contributors
// For license information, please see license.txt

frappe.query_reports["Vehicle Efficiency and Replacement"] = {
	filters: [
		{ fieldname: "from_date", label: __("From"), fieldtype: "Date", default: frappe.datetime.add_months(frappe.datetime.get_today(), -6) },
		{ fieldname: "to_date", label: __("To"), fieldtype: "Date", default: frappe.datetime.get_today() },
		{ fieldname: "ownership_type", label: __("Ownership"), fieldtype: "Select", options: ["", "Company-Owned", "External Supplier"] },
		{ fieldname: "company", label: __("Register Company"), fieldtype: "Link", options: "Company" },
		{ fieldname: "only_flagged", label: __("Only Vehicles With a Suggestion"), fieldtype: "Check" },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "suggestion" && data && data.suggestion) {
			const colour = data.suggestion.startsWith("Review") ? "red" : "orange";
			return `<span class="indicator-pill ${colour}">${frappe.utils.escape_html(data.suggestion)}</span>`;
		}
		return value;
	},
};
