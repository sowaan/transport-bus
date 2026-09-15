// Copyright (c) 2026, Sowaan and contributors
// For license information, please see license.txt

frappe.ui.form.on("Traffic Fine Staging", {
	refresh(frm) {
		if (frm.is_new()) return;

        // creating purchase invoice button

		if (!frm.is_new() && !frm.doc.is_invoiced) {

            frm.add_custom_button("Create Purchase Invoice", () => {

                frappe.confirm(
                    "Create a Purchase Invoice for this fine?",

                    () => {

                        frappe.call({
                            method: "create_purchase_invoice",
                            doc: frm.doc,
							
                            freeze: true,
                            freeze_message: "Creating Purchase Invoice...",

                            callback: function(r) {

                                if (!r.exc && r.message) {

                                    frappe.show_alert({
                                        message:
                                            `Purchase Invoice ${r.message} created successfully`,
                                        indicator: "green"
                                    });

                                    // Reload the document.
                                    // This will make is_invoiced = 1
                                    // and therefore remove the button.
                                    frm.reload_doc();
                                }
                            }
                        });

                    }
                );

            });
        }
	}
});
