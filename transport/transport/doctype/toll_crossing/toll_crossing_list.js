// Copyright (c) 2026, Sowaan and contributors
// For license information, please see license.txt

frappe.listview_settings["Toll Crossing"] = {
	add_fields: ["purchase_invoice", "vehicle"],
	get_indicator(doc) {
		if (doc.purchase_invoice) return [__("Invoiced"), "green", "purchase_invoice,is,set"];
		if (!doc.vehicle) return [__("No Vehicle"), "orange", "vehicle,is,not set"];
		return [__("To Invoice"), "gray", "purchase_invoice,is,not set"];
	},
	onload(listview) {
		listview.page.add_action_item(__("Create Purchase Invoice"), () => {
			const names = listview.get_checked_items(true);
			if (!names.length) {
				frappe.msgprint(__("Tick the crossings to invoice first."));
				return;
			}
			// transport.toll comes from the form script, which Frappe loads with
			// the doctype for the list as well.
			transport.toll.create_purchase_invoices(names, () => listview.refresh());
		});
	},
};
