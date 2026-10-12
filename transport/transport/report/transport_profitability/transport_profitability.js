// Copyright (c) 2026, Sowaan and contributors
// For license information, please see license.txt

frappe.query_reports["Transport Profitability"] = {
	filters: [
		{
			fieldname: "group_by",
			label: __("Group By"),
			fieldtype: "Select",
			options: ["Vehicle", "Driver", "Trip", "Project", "Outsourced Vehicle"],
			default: "Vehicle",
		},
		{ fieldname: "from_date", label: __("From"), fieldtype: "Date", default: frappe.datetime.add_months(frappe.datetime.get_today(), -1) },
		{ fieldname: "to_date", label: __("To"), fieldtype: "Date", default: frappe.datetime.get_today() },
		{ fieldname: "project", label: __("Project"), fieldtype: "Link", options: "Project" },
		{ fieldname: "vehicle", label: __("Vehicle"), fieldtype: "Link", options: "Rental Vehicle" },
		{ fieldname: "driver", label: __("Driver"), fieldtype: "Link", options: "Driver" },
		{ fieldname: "result", label: __("Result"), fieldtype: "Select", options: ["", "Loss", "Profit", "Not invoiced"] },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "result" && data) {
			const colours = { Loss: "red", Profit: "green", "Not invoiced": "orange" };
			return `<span class="indicator-pill ${colours[data.result] || "gray"}">${data.result}</span>`;
		}
		if (column.fieldname === "profit" && data && data.profit < 0) {
			return `<span style="color: var(--red-500)">${value}</span>`;
		}
		return value;
	},
};
