// Copyright (c) 2026, Sowaan and contributors
// For license information, please see license.txt

// The cost lines a Cost Master can fill in. Each is filled only while it is still
// empty - or while it still holds the figure the master put there - so a number the
// estimator typed over is never replaced behind their back.
const MASTER_COSTS = [
	"vehicle_rental_cost",
	"fuel_cost",
	"salik_toll_parking_cost",
	"driver_salary_cost",
	"room_rent_cost",
	"maintenance_cost",
];

const row_cost_total = (row) => MASTER_COSTS.reduce((sum, f) => sum + flt(row[f]), 0);

function apply_master_costs(frm, cdt, cdn, overwrite) {
	const row = locals[cdt][cdn];
	if (!(row.vehicle_category && row.seating_capacity)) {
		return;
	}
	frm.__auto_costs = frm.__auto_costs || {};
	const auto = (frm.__auto_costs[cdn] = frm.__auto_costs[cdn] || {});

	frappe
		.call({
			method: "transport.transport.doctype.transport_rate_calculation.transport_rate_calculation.get_cost_defaults",
			args: {
				vehicle_category: row.vehicle_category,
				seating_capacity: row.seating_capacity,
				ownership_type: row.ownership_type,
				with_driver: row.with_driver,
				with_fuel: row.with_fuel,
				km_per_day: row.km_per_day,
				working_days_per_month: row.working_days_per_month,
				on_date: frm.doc.transaction_date,
			},
		})
		.then((r) => {
			const result = r.message || {};
			if (!result.found) {
				frappe.show_alert({ message: result.message, indicator: "orange" }, 8);
				return;
			}
			Object.entries(result.values).forEach(([field, value]) => {
				const current = flt(row[field]);
				if (overwrite || !current || current === flt(auto[field])) {
					auto[field] = flt(value);
					frappe.model.set_value(cdt, cdn, field, flt(value));
				}
			});
			frappe.show_alert({ message: result.notes.join("; "), indicator: "green" }, 8);
			apply_required_margin(frm, cdt, cdn);
		});
}

// A margin typed on the row prices it: proposed = cost x (1 + margin / 100).
function apply_required_margin(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	if (flt(row.required_margin_percent)) {
		frappe.model.set_value(cdt, cdn, "proposed_price", flt(row_cost_total(row) * (1 + flt(row.required_margin_percent) / 100), 2));
	}
}

function fill_distance(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	if (!(row.from_place && row.to_place)) {
		return;
	}
	frappe.model.set_value(cdt, cdn, "route_from", row.from_place);
	frappe.model.set_value(cdt, cdn, "route_to", row.to_place);
	frappe
		.call({
			method: "transport.transport.doctype.transport_rate_calculation.transport_rate_calculation.get_route_distance",
			args: { from_place: row.from_place, to_place: row.to_place },
		})
		.then((r) => {
			const result = r.message || {};
			frappe.model.set_value(cdt, cdn, "distance_note", result.note || "");
			if (!result.km) {
				return;
			}
			// One way, there and back, for as many trips as the row is priced at.
			const per_day = flt(result.km * 2 * (flt(row.trips_per_day) || 1), 1);
			frm.__auto_costs = frm.__auto_costs || {};
			const auto = (frm.__auto_costs[cdn] = frm.__auto_costs[cdn] || {});
			if (!flt(row.km_per_day) || flt(row.km_per_day) === flt(auto.km_per_day)) {
				auto.km_per_day = per_day;
				frappe.model.set_value(cdt, cdn, "km_per_day", per_day);
			}
		});
}

frappe.ui.form.on("Transport Rate Calculation Vehicle", {
	vehicle_category: (frm, cdt, cdn) => apply_master_costs(frm, cdt, cdn, false),
	seating_capacity: (frm, cdt, cdn) => apply_master_costs(frm, cdt, cdn, false),
	ownership_type: (frm, cdt, cdn) => apply_master_costs(frm, cdt, cdn, false),
	with_driver: (frm, cdt, cdn) => apply_master_costs(frm, cdt, cdn, false),
	with_fuel: (frm, cdt, cdn) => apply_master_costs(frm, cdt, cdn, false),
	km_per_day: (frm, cdt, cdn) => apply_master_costs(frm, cdt, cdn, false),
	working_days_per_month: (frm, cdt, cdn) => apply_master_costs(frm, cdt, cdn, false),
	from_place: fill_distance,
	to_place: fill_distance,
	required_margin_percent: apply_required_margin,
	vehicle_rental_cost: apply_required_margin,
	fuel_cost: apply_required_margin,
	salik_toll_parking_cost: apply_required_margin,
	driver_salary_cost: apply_required_margin,
	room_rent_cost: apply_required_margin,
	maintenance_cost: apply_required_margin,
});

frappe.ui.form.on("Transport Rate Calculation", {
	refresh(frm) {
		if (frm.doc.docstatus === 0 && (frm.doc.vehicles || []).length) {
			frm.add_custom_button(__("Refresh Costs from Cost Master"), () => {
				frappe.confirm(
					__("Replace the cost figures on every vehicle with the Cost Master's? Anything you typed over will be replaced."),
					() => (frm.doc.vehicles || []).forEach((row) => apply_master_costs(frm, row.doctype, row.name, true))
				);
			});
		}
		if (frm.is_new() || frm.doc.quotation) {
			return;
		}

		if (!frm.doc.customer || !frm.doc.total_final_price) {
			return;
		}

		frm.add_custom_button(__("Create Quotation"), () => {
			frappe.confirm(
				__("Create a Quotation for {0} covering {1} vehicle(s), totalling {2}?", [
					frm.doc.customer,
					(frm.doc.vehicles || []).length,
					format_currency(frm.doc.total_final_price),
				]),
				() => {
					frm.call("create_quotation").then((r) => {
						if (!r.exc) {
							frm.reload_doc();
							frappe.set_route("Form", "Quotation", r.message);
						}
					});
				}
			);
		});
	},
});
