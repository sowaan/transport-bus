// Copyright (c) 2026, Sowaan and contributors
// For license information, please see license.txt

frappe.query_reports["Vehicle Inspection Grid"] = {
	filters: [
		{ fieldname: "vehicle", label: __("Vehicle"), fieldtype: "Link", options: "Rental Vehicle", reqd: 1 },
		{
			fieldname: "month",
			label: __("Month"),
			fieldtype: "Select",
			options: ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
			default: ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"][new Date().getMonth()],
		},
		{ fieldname: "year", label: __("Year"), fieldtype: "Int", default: new Date().getFullYear() },
	],

	// G good, F fair, P poor - coloured so a bad day stands out on the sheet.
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		const colours = { G: "var(--green-600)", F: "var(--orange-500)", P: "var(--red-500)" };
		const raw = data && data[column.fieldname];
		if (column.fieldname.match(/^d\d+$/) && colours[raw]) {
			return `<span style="color: ${colours[raw]}; font-weight: 700; display: block; text-align: center">${raw}</span>`;
		}
		return value;
	},
};
