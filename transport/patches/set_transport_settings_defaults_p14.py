import frappe

DOCTYPE = "Transport Settings"

DEFAULTS = {"road_distance_factor": 1.3}


def execute():
	"""Seed the road distance factor used to turn a straight-line distance between
	two Places into a driving estimate. Row presence is what is tested - see
	set_transport_settings_defaults_p9."""
	for fieldname, value in DEFAULTS.items():
		already_set = frappe.db.sql(
			"select 1 from tabSingles where doctype = %s and field = %s limit 1", (DOCTYPE, fieldname)
		)
		if not already_set:
			frappe.db.set_single_value(DOCTYPE, fieldname, value)
