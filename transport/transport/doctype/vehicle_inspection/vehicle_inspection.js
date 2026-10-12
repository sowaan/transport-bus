// Copyright (c) 2026, Sowaan and contributors
// For license information, please see license.txt

// A new inspection opens with its list already in place: the 17 daily check
// points, or the vehicle OUT / IN checklist, depending on the type. Switching
// type re-fills them - but only while the form is new and nothing has been
// ticked or graded, so work in progress is never overwritten.
const inspection_is_untouched = (frm) =>
	!(frm.doc.check_points || []).some((row) => row.condition || row.remarks) &&
	!(frm.doc.handover_checklist || []).some((row) => row.present || row.remarks);

const seed_inspection_lists = (frm) => {
	if (!frm.is_new() || !inspection_is_untouched(frm)) {
		return;
	}
	frappe.call({
		method: "transport.transport.doctype.vehicle_inspection.vehicle_inspection.get_inspection_lists",
		args: { inspection_type: frm.doc.inspection_type },
		callback: (r) => {
			const lists = r.message || {};
			frm.clear_table("check_points");
			(lists.check_points || []).forEach((row) => frm.add_child("check_points", row));
			frm.clear_table("handover_checklist");
			(lists.handover_checklist || []).forEach((row) => frm.add_child("handover_checklist", row));
			frm.refresh_field("check_points");
			frm.refresh_field("handover_checklist");
		},
	});
};

frappe.ui.form.on("Vehicle Inspection", {
	onload(frm) {
		seed_inspection_lists(frm);
	},

	inspection_type(frm) {
		seed_inspection_lists(frm);
	},
});
