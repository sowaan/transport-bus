import frappe

DOCTYPE = "Transport Settings"

DEFAULTS = {
	"expiry_alert_days": "30,15,7",
	"asateel_permit_alert_days": "15",
	"po_expiry_alert_days": 30,
	"po_consumed_alert_percent": 80,
	"service_reminder_days": 7,
}

# The client's 07-Oct UAT note states the overtime trip limits outright: more than
# 7 trips for LMV and more than 5 for HMV. These replace the earlier 5 and 4 -
# but only where the site is still on those numbers, so a limit someone has
# already tuned by hand is not overwritten.
OT_TRIP_LIMITS = {
	"lmv_daily_trip_limit": (5, 7),
	"hmv_daily_trip_limit": (4, 5),
}


def _stored(fieldname):
	row = frappe.db.sql(
		"select value from tabSingles where doctype = %s and field = %s limit 1", (DOCTYPE, fieldname)
	)
	return row[0][0] if row else None


def execute():
	"""Seed the alert settings and move the overtime trip limits to the client's.

	Same shape as p7-p10, for the same reason: a `default` in the DocType JSON
	never reaches tabSingles until the Single is saved once, and get_single_value
	cannot tell "never configured" from "set to zero", so presence of the row is
	what is tested."""
	for fieldname, value in DEFAULTS.items():
		if _stored(fieldname) is None:
			frappe.db.set_single_value(DOCTYPE, fieldname, value)

	for fieldname, (old, new) in OT_TRIP_LIMITS.items():
		current = _stored(fieldname)
		if current is None or int(float(current)) == old:
			frappe.db.set_single_value(DOCTYPE, fieldname, new)
