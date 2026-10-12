// Copyright (c) 2026, Sowaan and contributors
// For license information, please see license.txt

// The criteria table is mandatory, so Frappe shows one blank row on a new form
// and the standard heads used to appear only after the first save. Fill them in
// as soon as the form opens, and again if the scorer changes (Supervisor / Admin
// scores ten heads out of 10, Customer six out of 5) - but never over a form
// somebody has already started scoring.
const evaluation_has_scores = (frm) =>
	(frm.doc.criteria || []).some((row) => row.score_given !== null && row.score_given !== undefined && row.score_given !== "");

const seed_evaluation_criteria = (frm) => {
	if (!frm.is_new() || evaluation_has_scores(frm)) {
		return;
	}
	frappe.call({
		method: "transport.transport.doctype.driver_monthly_evaluation.driver_monthly_evaluation.get_criteria",
		args: { evaluation_type: frm.doc.evaluation_type },
		callback: (r) => {
			frm.clear_table("criteria");
			(r.message || []).forEach((row) => frm.add_child("criteria", row));
			frm.refresh_field("criteria");
		},
	});
};

frappe.ui.form.on("Driver Monthly Evaluation", {
	onload(frm) {
		seed_evaluation_criteria(frm);
	},

	evaluation_type(frm) {
		seed_evaluation_criteria(frm);
	},
});
