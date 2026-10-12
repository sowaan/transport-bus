// Copyright (c) 2026, Sowaan and contributors
// For license information, please see license.txt

// The list reads as a status board: each vehicle, and the stage its renewal is at.
frappe.listview_settings["Vehicle Renewal"] = {
	add_fields: ["status", "current_stage"],
	get_indicator(doc) {
		if (doc.status === "Completed") {
			return [__("Completed"), "green", "status,=,Completed"];
		}
		if (doc.status === "Cancelled") {
			return [__("Cancelled"), "grey", "status,=,Cancelled"];
		}
		return [doc.current_stage || __("In Progress"), "orange", "status,=,In Progress"];
	},
};
