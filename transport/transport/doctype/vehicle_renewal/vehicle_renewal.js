// Copyright (c) 2026, Sowaan and contributors
// For license information, please see license.txt

frappe.ui.form.on("Vehicle Renewal", {
	refresh(frm) {
		if (!frm.is_new() && frm.doc.status === "In Progress") {
			frm.add_custom_button(__("Complete Renewal"), () => {
				frappe.confirm(
					__("Put the new expiry dates and fees on {0} and close this renewal?", [frm.doc.vehicle]),
					() => frm.call("complete").then(() => frm.reload_doc())
				);
			});
		}
	},
});
