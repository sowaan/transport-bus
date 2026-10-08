// Copyright (c) 2026, Sowaan and contributors
// For license information, please see license.txt

frappe.ui.form.on("Toll Tariff", {
	validate(frm) {
		// The server cannot tell a blank Time from one typed as "now" (Frappe
		// fills blanks before validate runs), so a blank Toll time is caught here.
		(frm.doc.rates || []).forEach((row) => {
			if (row.kind === "Toll" && (!row.from_time || !row.to_time)) {
				frappe.throw(__("Row {0}: a Toll rate needs both From and To times.", [row.idx]));
			}
		});
	},
});
