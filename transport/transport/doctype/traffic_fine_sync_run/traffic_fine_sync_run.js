// Copyright (c) 2026, Sowaan and contributors
// For license information, please see license.txt

frappe.ui.form.on("Traffic Fine Sync Run", {
	refresh(frm) {
		if (frm.is_new()) return;

		if (frm.doc.status === "Completed with Errors") {
			frm.dashboard.set_headline(
				__("{0} vehicle(s) could not be queried. Their fines are unknown, not zero.", [
					frm.doc.vehicles_failed,
				])
			);
		}

		frm.add_custom_button(__("View Staged Fines"), () => {
			frappe.set_route("List", "Traffic Fine Staging", { sync_run: frm.doc.name });
		});
	},
});
