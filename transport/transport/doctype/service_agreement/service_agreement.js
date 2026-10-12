// Copyright (c) 2026, Sowaan and contributors
// For license information, please see license.txt

frappe.ui.form.on("Service Agreement", {
	tc_name(frm) {
		if (!frm.doc.tc_name) {
			return;
		}
		frappe.db.get_value("Terms and Conditions", frm.doc.tc_name, "terms").then((r) => {
			if (r.message && r.message.terms) {
				frm.set_value("terms", r.message.terms);
			}
		});
	},
});
