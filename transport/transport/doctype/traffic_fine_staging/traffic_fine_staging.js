// Copyright (c) 2026, Sowaan and contributors
// For license information, please see license.txt

frappe.ui.form.on("Traffic Fine Staging", {
	refresh(frm) {
		if (frm.is_new()) return;

		name_the_reference(frm);

		// "Is Invoiced" is kept in step with whether an invoice actually stands
		// (see transport/transport/fine_invoice.py), so this button comes back
		// on its own once the invoice is cancelled or deleted. That is the
		// whole of the re-creation requirement, and it needs nothing here
		// beyond reading the flag.
		if (!frm.doc.is_invoiced) {
			frm.add_custom_button(__("Create Purchase Invoice"), () => {
				frappe.confirm(__("Create a Purchase Invoice for this fine?"), () => {
					frm.call({
						method: "create_purchase_invoice",
						doc: frm.doc,
						freeze: true,
						freeze_message: __("Creating Purchase Invoice..."),
					}).then((r) => {
						if (!r.exc && r.message) frm.reload_doc();
					});
				});
			});
		} else {
			frm.add_custom_button(__("View Purchase Invoice"), () => {
				frappe.set_route("List", "Purchase Invoice", {
					custom_traffic_fine_staging: frm.doc.name,
				});
			});
		}

		// Vehicle is read-only because it is our match, not the portal's word.
		// A wrong or missing match is a plate that disagrees with the fleet
		// record, so the fix belongs on the Rental Vehicle - then this.
		if (!frm.doc.vehicle) {
			frm.add_custom_button(__("Match Vehicle"), () => {
				frm.call({ method: "rematch_vehicle", doc: frm.doc, freeze: true }).then(
					(r) => {
						if (!r.exc && r.message) frm.reload_doc();
					}
				);
			});
		}
	},
});

// Portals do not agree on what a fine's reference number is called: TAMM says
// Fine Number, RTA says Ticket Number. The figure is stored in one field, since
// it is one fact and the duplicate check depends on it, but it is labelled
// here with whatever the portal it came from calls it - so the number on this
// form is named the same as the number on the page being reconciled against.
function name_the_reference(frm) {
	const label = frm.doc.reference_label;
	if (label) frm.set_df_property("ticket_number", "label", __(label));
}
