// Copyright (c) 2026, Sowaan and contributors
// For license information, please see license.txt

frappe.listview_settings["Transport Request"] = {
	add_fields: ["status", "charge"],
	get_indicator(doc) {
		const colours = { Open: "orange", Invoiced: "green", Cancelled: "grey" };
		return [__(doc.status), colours[doc.status] || "grey", "status,=," + doc.status];
	},

	// Month end: pick the company and a day in the month; every open request of
	// theirs in that month goes onto one Sales Invoice.
	onload(listview) {
		const accounts = ["Transport Accounts", "System Manager"].some((r) => frappe.user.has_role(r));
		if (!accounts) {
			return;
		}
		listview.page.add_inner_button(__("Create Monthly Invoice"), () => {
			frappe.prompt(
				[
					{ fieldname: "customer", label: __("Requesting Company"), fieldtype: "Link", options: "Customer", reqd: 1 },
					{
						fieldname: "month",
						label: __("Any Date in the Month"),
						fieldtype: "Date",
						reqd: 1,
						default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
					},
					{ fieldname: "company", label: __("Invoice From Company"), fieldtype: "Link", options: "Company" },
				],
				(values) => {
					frappe.call({
						method: "transport.transport.doctype.transport_request.transport_request.create_monthly_invoice",
						args: values,
						freeze: true,
						callback: (r) => {
							if (r.message) {
								frappe.show_alert({ message: __("{0} request(s) invoiced", [r.message.requests]), indicator: "green" });
								frappe.set_route("Form", "Sales Invoice", r.message.invoice);
							}
						},
					});
				},
				__("Create Monthly Invoice"),
				__("Create")
			);
		});
	},
};
