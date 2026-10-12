// Copyright (c) 2026, Sowaan and contributors
// For license information, please see license.txt

// The Trip's status leads each row of the list, in a colour that says what
// needs doing: grey = still being planned, blue = with the driver, orange =
// on the road, green = ready to bill.
frappe.listview_settings["Trip"] = {
	add_fields: ["status", "needs_reallocation", "duty_type"],
	get_indicator(doc) {
		if (doc.needs_reallocation && !["Approved", "Cancelled"].includes(doc.status)) {
			return [__("Needs Reallocation"), "red", "needs_reallocation,=,1"];
		}
		const colours = {
			Draft: "gray",
			Assigned: "blue",
			Accepted: "cyan",
			Rejected: "red",
			Started: "orange",
			Completed: "green",
			Approved: "purple",
			Cancelled: "darkgrey",
		};
		return [__(doc.status), colours[doc.status] || "gray", "status,=," + doc.status];
	},

	// The "Assign driver" / "Assign vehicle" quick actions: pick trips, pick one
	// driver or vehicle, and every trip that can take it does.
	onload(listview) {
		const office = ["Transport In-Charge", "Transport Operations", "System Manager"].some((r) =>
			frappe.user.has_role(r)
		);
		if (!office) {
			return;
		}
		const assign = (field, label) => {
			const names = listview.get_checked_items(true);
			if (!names.length) {
				frappe.msgprint(__("Tick the trips first."));
				return;
			}
			frappe.prompt(
				[{ fieldname: "value", label: __(label), fieldtype: "Link", options: field === "driver" ? "Driver" : "Rental Vehicle", reqd: 1 }],
				(values) => {
					frappe.call({
						method: "transport.transport.operations.bulk_assign",
						args: { trip_names: names, [field]: values.value },
						freeze: true,
						callback: (r) => {
							const result = r.message || {};
							const failed = (result.failed || []).map((f) => `${f.trip}: ${f.error}`).join("<br>");
							frappe.msgprint({
								title: __("Assigned"),
								indicator: failed ? "orange" : "green",
								message: __("{0} trip(s) updated.", [(result.done || []).length]) + (failed ? "<br><br>" + failed : ""),
							});
							listview.refresh();
						},
					});
				},
				__(label),
				__("Assign")
			);
		};
		listview.page.add_actions_menu_item(__("Assign Driver"), () => assign("driver", "Driver"), false);
		listview.page.add_actions_menu_item(__("Assign Vehicle"), () => assign("vehicle", "Vehicle"), false);
	},
};
