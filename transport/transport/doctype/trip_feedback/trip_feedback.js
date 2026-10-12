// Copyright (c) 2026, Sowaan and contributors
// For license information, please see license.txt

// Fill the scoring heads as soon as the form opens, and again when the scorer
// changes - Customer scores six heads out of 5, everyone else ten out of 10 -
// but never over a form somebody has already started scoring, and never on a
// record saved with the earlier six fixed fields.
const feedback_has_scores = (frm) =>
	(frm.doc.criteria || []).some((row) => row.score_given !== null && row.score_given !== undefined && row.score_given !== "");

const seed_feedback_criteria = (frm) => {
	if (!frm.is_new() || feedback_has_scores(frm)) {
		return;
	}
	frappe.call({
		method: "transport.transport.doctype.trip_feedback.trip_feedback.get_criteria",
		args: { feedback_from: frm.doc.feedback_from },
		callback: (r) => {
			frm.clear_table("criteria");
			(r.message || []).forEach((row) => frm.add_child("criteria", row));
			frm.refresh_field("criteria");
		},
	});
};

frappe.ui.form.on("Trip Feedback", {
	onload(frm) {
		seed_feedback_criteria(frm);
	},

	feedback_from(frm) {
		seed_feedback_criteria(frm);
	},
});
