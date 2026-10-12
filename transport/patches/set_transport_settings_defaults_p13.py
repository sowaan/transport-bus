import frappe

DOCTYPE = "Transport Settings"

# Switched on by default - it is one of the client's listed mandatory controls and
# is harmless to a project that has described no locations yet. The budget
# requirement is deliberately NOT seeded: it needs Budgets to exist first.
DEFAULTS = {"restrict_trip_places_to_project": 1}


def execute():
	"""Seed the location control. See set_transport_settings_defaults_p9 for why the
	presence of the tabSingles row, not get_single_value, is what is tested."""
	for fieldname, value in DEFAULTS.items():
		already_set = frappe.db.sql(
			"select 1 from tabSingles where doctype = %s and field = %s limit 1", (DOCTYPE, fieldname)
		)
		if not already_set:
			frappe.db.set_single_value(DOCTYPE, fieldname, value)
