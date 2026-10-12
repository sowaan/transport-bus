// Copyright (c) 2026, Sowaan and contributors
// For license information, please see license.txt

frappe.query_reports["Company Vehicle List"] = {
	filters: [
		{ fieldname: "company", label: __("Register Company"), fieldtype: "Link", options: "Company" },
		{
			fieldname: "ownership_type",
			label: __("Ownership"),
			fieldtype: "Select",
			options: ["", "Company-Owned", "External Supplier"],
		},
		{
			fieldname: "expiring_in_days",
			label: __("Mulkiya / Insurance Expires Within (days)"),
			fieldtype: "Int",
			description: __("Includes anything already expired."),
		},
	],

	// Expired in red, due within 30 days in orange - the two dates the list exists to watch.
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (["registration_expiry", "insurance_expiry"].includes(column.fieldname) && data && data[column.fieldname]) {
			const days = frappe.datetime.get_diff(data[column.fieldname], frappe.datetime.get_today());
			if (days < 0) {
				return `<span style="color: var(--red-500); font-weight: 600">${value}</span>`;
			}
			if (days <= 30) {
				return `<span style="color: var(--orange-500); font-weight: 600">${value}</span>`;
			}
		}
		return value;
	},
};
