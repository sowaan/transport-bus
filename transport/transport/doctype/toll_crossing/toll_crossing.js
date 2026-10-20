// Copyright (c) 2026, Sowaan and contributors
// For license information, please see license.txt

frappe.ui.form.on("Toll Crossing", {
	refresh(frm) {
		if (frm.is_new()) return;

		if (frm.doc.purchase_invoice) {
			frm.add_custom_button(__("View Purchase Invoice"), () =>
				frappe.set_route("Form", "Purchase Invoice", frm.doc.purchase_invoice)
			);
			return;
		}

		frm.add_custom_button(__("Create Purchase Invoice"), () =>
			transport.toll.create_purchase_invoices([frm.doc.name], () => frm.reload_doc())
		);
	},
});

// Shared with the list's bulk action (toll_crossing_list.js): one call, any
// number of crossings, grouped per vehicle on the server.
frappe.provide("transport.toll");
transport.toll.create_purchase_invoices = function (names, done) {
	frappe.confirm(
		__("Create Purchase Invoices for {0} toll crossing(s)? One invoice is made per vehicle.", [names.length]),
		() => {
			frappe.call({
				method: "transport.transport.toll_invoice.create_purchase_invoices",
				args: { names },
				freeze: true,
				freeze_message: __("Creating Purchase Invoices..."),
				callback(r) {
					if (r.exc || !r.message) return;
					transport.toll.report(r.message);
					if (done) done();
				},
			});
		}
	);
};

transport.toll.report = function ({ invoices, skipped, failed }) {
	const link = (dt, name) => frappe.utils.get_form_link(dt, name, true);
	const parts = [];

	if (invoices.length) {
		parts.push(
			`<p><b>${__("Created")}</b></p><ul>` +
				invoices
					.map(
						(i) =>
							`<li>${link("Purchase Invoice", i.invoice)} - ${frappe.utils.escape_html(i.vehicle)}, ` +
							`${i.count} ${__("crossing(s)")}</li>`
					)
					.join("") +
				"</ul>"
		);
	}
	if (skipped.length) {
		parts.push(
			`<p><b>${__("Left out")}</b></p><ul>` +
				skipped
					.map((s) => `<li>${link("Toll Crossing", s.name)} - ${frappe.utils.escape_html(s.reason)}</li>`)
					.join("") +
				"</ul>"
		);
	}
	if (failed.length) {
		parts.push(
			`<p><b>${__("Failed")}</b></p><ul>` +
				failed
					.map(
						(f) =>
							`<li>${frappe.utils.escape_html(f.vehicle)} / ${frappe.utils.escape_html(f.authority)}: ` +
							`${frappe.utils.escape_html(f.error)}</li>`
					)
					.join("") +
				"</ul>"
		);
	}

	frappe.msgprint({
		title: __("Toll Purchase Invoices"),
		message: parts.join("") || __("Nothing to invoice."),
		indicator: failed.length ? "orange" : "green",
		wide: true,
	});
};
