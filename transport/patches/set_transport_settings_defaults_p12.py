import frappe

DOCTYPE = "Transport Settings"

DEFAULTS = {
	# Below this many round trips a month is billed per trip (UAT note, 07-Oct).
	"monthly_round_trip_threshold": 10,
	# The client wants the timesheet to appear when a trip is approved.
	"auto_create_timesheet_on_approval": 1,
}


def execute():
	"""Seed the two settings added with the per-trip billing rule and the automatic
	timesheet. Presence of the tabSingles row is what is tested, for the reason
	set_transport_settings_defaults_p9 gives: get_single_value cannot tell "never
	configured" from "deliberately off"."""
	for fieldname, value in DEFAULTS.items():
		already_set = frappe.db.sql(
			"select 1 from tabSingles where doctype = %s and field = %s limit 1", (DOCTYPE, fieldname)
		)
		if not already_set:
			frappe.db.set_single_value(DOCTYPE, fieldname, value)
