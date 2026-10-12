// Copyright (c) 2026, Sowaan and contributors
// For license information, please see license.txt

frappe.query_reports["Driver Violations and Black Points"] = {
	filters: [
		{ fieldname: "view", label: __("View"), fieldtype: "Select", options: ["Summary", "Fines & Incidents"], default: "Summary" },
		{ fieldname: "driver", label: __("Driver"), fieldtype: "Link", options: "Driver" },
		{ fieldname: "from_date", label: __("From"), fieldtype: "Date" },
		{ fieldname: "to_date", label: __("To"), fieldtype: "Date" },
		{
			fieldname: "standing",
			label: __("Standing"),
			fieldtype: "Select",
			options: ["", "Blacklisted", "Bad", "Watch", "Good"],
		},
		{ fieldname: "only_with_history", label: __("Only Drivers With a History"), fieldtype: "Check" },
	],

	// Good drivers green, drivers to worry about orange / red - the highlight the client asked for.
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "standing" && data) {
			const colours = { Good: "green", Watch: "orange", Bad: "red", Blacklisted: "red" };
			return `<span class="indicator-pill ${colours[data.standing] || "gray"}">${data.standing}</span>`;
		}
		return value;
	},
};
