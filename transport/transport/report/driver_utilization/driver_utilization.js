// Copyright (c) 2026, Sowaan and contributors
// For license information, please see license.txt

frappe.query_reports["Driver Utilization"] = {
	filters: [
		{ fieldname: "from_date", label: __("From"), fieldtype: "Date", default: frappe.datetime.add_months(frappe.datetime.get_today(), -1) },
		{ fieldname: "to_date", label: __("To"), fieldtype: "Date", default: frappe.datetime.get_today() },
		{ fieldname: "driver", label: __("Driver"), fieldtype: "Link", options: "Driver" },
		{ fieldname: "utilization", label: __("Utilization"), fieldtype: "Select", options: ["", "Over-utilized", "Under-utilized", "Balanced"] },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "utilization" && data) {
			const colours = { "Over-utilized": "red", "Under-utilized": "orange", Balanced: "green" };
			return `<span class="indicator-pill ${colours[data.utilization] || "gray"}">${data.utilization}</span>`;
		}
		return value;
	},
};
