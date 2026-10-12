// Copyright (c) 2026, Sowaan and contributors
// For license information, please see license.txt

frappe.ui.form.on("Trip", {
	refresh(frm) {
		/*frm.set_query("vehicle", () => ({
			query: "transport.transport.doctype.trip.trip.get_available_vehicles",
			filters: {
				trip_date: frm.doc.trip_date,
				scheduled_time: frm.doc.scheduled_time,
				vehicle_category: frm.doc.route ? frappe.db.get_value("Route", frm.doc.route, "vehicle_category") : null,
			},
		})); */

		frm.set_query("driver", () => ({
			query: "transport.transport.doctype.trip.trip.get_available_drivers",
			filters: {
				trip_date: frm.doc.trip_date,
				scheduled_time: frm.doc.scheduled_time,
			},
		}));

		const is_office = ["Transport In-Charge", "Transport Operations", "System Manager"].some(
			(role) => frappe.user.has_role(role)
		);

		// The quick actions the client asked for: assign / reassign, find a vehicle,
		// and ring the driver.
		if (!frm.is_new() && frm.doc.driver) {
			frm.add_custom_button(__("Call Driver"), () => call_trip_driver(frm), __("Quick Actions"));
		}
		if (!frm.is_new() && is_office && ["Draft", "Assigned", "Accepted", "Rejected"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Reallocate"), () => reallocate_trip_dialog(frm), __("Quick Actions"));
		}
		if (is_office && ["Draft", "Assigned", "Accepted", "Rejected"].includes(frm.doc.status || "Draft")) {
			frm.add_custom_button(__("Suggest Vehicle"), () => suggest_vehicle_dialog(frm), __("Quick Actions"));
		}

		if (!frm.is_new() && frm.doc.status === "Completed" && is_office) {
			frm.add_custom_button(__("Approve"), () => {
				frappe.call({
					method: "transport.transport.operations.approve_trip",
					args: { trip_name: frm.doc.name },
					callback: () => frm.reload_doc(),
				});
			});
		}

		// Starting from the desk is for a driver who is not using the portal -
		// one who phones in, or who has no portal account. The driver's own
		// start asks for a vehicle photo and checks their position against the
		// pickup point; neither exists here, so the odometer is all this can
		// ask for and it stays optional.
		// Ending from the desk, same trade as starting: the driver's own end asks
		// for a photo of the drop location, which nobody at a desk has. Unlike
		// the Server Script this replaces, the app method also recalculates
		// duration and Duty/OT from the actual times - without that the trip
		// stays costed on its planned hours.
		if (!frm.is_new() && frm.doc.status === "Started" && is_office) {
			frm.add_custom_button(__("End Trip"), () => {
				frappe.prompt(
					[
						{
							fieldname: "end_odometer",
							label: __("End odometer (km)"),
							fieldtype: "Float",
							description: frm.doc.start_odometer
								? __("Started at {0} km", [frm.doc.start_odometer])
								: "",
						},
						{
							fieldname: "driver_remarks",
							label: __("Remarks"),
							fieldtype: "Small Text",
						},
					],
					(values) => {
						frappe.call({
							method: "transport.transport.operations.end_trip",
							args: {
								trip_name: frm.doc.name,
								end_odometer: values.end_odometer || null,
								driver_remarks: values.driver_remarks || null,
							},
							freeze: true,
							callback: () => frm.reload_doc(),
						});
					},
					__("End this trip"),
					__("End")
				);
			});
		}

		if (!frm.is_new() && ["Assigned", "Accepted"].includes(frm.doc.status) && is_office) {
			frm.add_custom_button(__("Start Trip"), () => {
				frappe.prompt(
					{
						fieldname: "start_odometer",
						label: __("Start odometer (km)"),
						fieldtype: "Float",
						reqd: 0,
					},
					(values) => {
						frappe.call({
							method: "transport.transport.operations.start_trip",
							args: {
								trip_name: frm.doc.name,
								start_odometer: values.start_odometer || null,
							},
							freeze: true,
							callback: () => frm.reload_doc(),
						});
					},
					__("Start this trip"),
					__("Start")
				);
			});
		}
	},

	// A vehicle brings its usual driver: the one allocated on the Project, else the
	// Assigned Driver on the vehicle. Never replaces a driver already chosen.
	vehicle(frm) {
		if (!frm.doc.vehicle || frm.doc.driver) {
			return;
		}
		frappe
			.call({
				method: "transport.transport.doctype.trip.trip.default_driver_for_vehicle",
				args: { vehicle: frm.doc.vehicle, project: frm.doc.project, shift: frm.doc.shift },
			})
			.then((r) => {
				if (r.message && !frm.doc.driver) {
					frm.set_value("driver", r.message);
				}
			});
	},

	route(frm) {
		if (!frm.doc.route) {
			return;
		}
		frappe.db.get_doc("Route", frm.doc.route).then((route) => {
			if (frm.doc.direction === "Drop") {
				frm.set_value("from_place", route.to_place);
				frm.set_value("to_place", route.from_place);
				frm.set_value("scheduled_time", frm.doc.scheduled_time || route.drop_time);
			} else {
				frm.set_value("from_place", route.from_place);
				frm.set_value("to_place", route.to_place);
				frm.set_value("scheduled_time", frm.doc.scheduled_time || route.pickup_time);
			}
			if (!frm.doc.project) {
				frm.set_value("project", route.project);
			}
		});
	},
});


// ---------------------------------------------------------------- quick actions

function call_trip_driver(frm) {
	frappe.db.get_value("Driver", frm.doc.driver, ["full_name", "cell_number"]).then((r) => {
		const driver = r.message || {};
		if (!driver.cell_number) {
			frappe.msgprint(__("{0} has no mobile number on file.", [driver.full_name || frm.doc.driver]));
			return;
		}
		// tel: opens the phone app on a handset and the default dialler on a desktop.
		window.location.href = "tel:" + driver.cell_number.replace(/\s+/g, "");
	});
}

function reallocate_trip_dialog(frm) {
	frappe.prompt(
		[
			{ fieldname: "driver", label: __("New Driver"), fieldtype: "Link", options: "Driver", default: frm.doc.driver },
			{ fieldname: "vehicle", label: __("New Vehicle"), fieldtype: "Link", options: "Rental Vehicle", default: frm.doc.vehicle },
			{ fieldname: "reason", label: __("Reason"), fieldtype: "Small Text", reqd: 1 },
		],
		(values) => {
			frappe.call({
				method: "transport.transport.operations.reallocate_trip",
				args: {
					trip_name: frm.doc.name,
					driver: values.driver !== frm.doc.driver ? values.driver : null,
					vehicle: values.vehicle !== frm.doc.vehicle ? values.vehicle : null,
					reason: values.reason,
				},
				freeze: true,
				callback: () => frm.reload_doc(),
			});
		},
		__("Reallocate this trip"),
		__("Reallocate")
	);
}

function suggest_vehicle_dialog(frm) {
	if (!frm.doc.trip_date) {
		frappe.msgprint(__("Set the Trip Date first."));
		return;
	}
	frappe
		.call({
			method: "transport.transport.operations.suggest_vehicles",
			args: {
				trip_date: frm.doc.trip_date,
				scheduled_time: frm.doc.scheduled_time,
				no_of_passengers: frm.doc.no_of_passengers,
			},
		})
		.then((r) => {
			const rows = r.message || [];
			if (!rows.length) {
				frappe.msgprint(__("No vehicle is free for that date and time with enough seats."));
				return;
			}
			const dialog = new frappe.ui.Dialog({
				title: __("Suggested Vehicles"),
				fields: [{ fieldtype: "HTML", fieldname: "list" }],
			});
			const html = rows
				.map(
					(v) => `<div style="padding:6px 0;border-bottom:1px solid var(--border-color)">
						<a href="#" class="pick-vehicle" data-vehicle="${frappe.utils.escape_html(v.vehicle)}"><b>${frappe.utils.escape_html(v.vehicle)}</b></a>
						${frappe.utils.escape_html(v.label || "")}
						${v.compliance_issue ? '<span class="indicator-pill red">' + __("check papers") + "</span>" : ""}
						<div class="text-muted small">${frappe.utils.escape_html(v.reasons)}</div></div>`
				)
				.join("");
			dialog.fields_dict.list.$wrapper.html(html);
			dialog.fields_dict.list.$wrapper.on("click", ".pick-vehicle", (e) => {
				e.preventDefault();
				frm.set_value("vehicle", e.currentTarget.dataset.vehicle);
				dialog.hide();
			});
			dialog.show();
		});
}
