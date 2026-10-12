// Copyright (c) 2026, Sowaan and contributors
// For license information, please see license.txt

frappe.ui.form.on("Transport Request", {
	refresh(frm) {
		frm.set_df_property("status", "read_only", 1);
		if (frm.doc.status === "Open" && !frm.is_new()) {
			frm.add_custom_button(__("Cancel Request"), () => {
				frappe.db.set_value("Transport Request", frm.doc.name, "status", "Cancelled").then(() => frm.reload_doc());
			});
		}
	},
});
