// Copyright (c) 2026, Sowaan and contributors
// For license information, please see license.txt

frappe.query_reports["Vehicle Condition Report"] = {
	filters: [
		{ fieldname: "vehicle", label: __("Vehicle"), fieldtype: "Link", options: "Rental Vehicle" },
		{ fieldname: "company", label: __("Register Company"), fieldtype: "Link", options: "Company" },
		{ fieldname: "condition", label: __("Condition"), fieldtype: "Select", options: ["", "Poor", "Fair", "Good", "Not inspected"] },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "condition" && data) {
			const colours = { Good: "green", Fair: "orange", Poor: "red", "Not inspected": "gray" };
			return `<span class="indicator-pill ${colours[data.condition] || "gray"}">${data.condition}</span>`;
		}
		return value;
	},
};
