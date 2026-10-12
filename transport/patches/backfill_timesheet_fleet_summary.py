import frappe

FIELDS = (
	"driver_names",
	"vehicle_details",
	"total_saturday_trips",
	"total_sunday_trips",
	"total_round_trips",
)


def execute():
	"""Fill the fields added to Transport Timesheet - drivers, vehicles, Saturday and
	Sunday trips, round trips - on timesheets that already exist.

	They are computed when a timesheet is saved, so an old one would otherwise show
	them blank, and invoicing reads Round Trips for the below-10 per-trip rule: a
	stored zero would switch that rule off for a timesheet that was already waiting
	for approval. Written straight to the columns, not by saving - re-saving would
	re-run the push of manual edits back to the trips and restamp the record."""
	for name in frappe.get_all("Transport Timesheet", pluck="name"):
		timesheet = frappe.get_doc("Transport Timesheet", name)
		timesheet.calculate_totals()
		timesheet.set_fleet_summary()
		frappe.db.set_value(
			"Transport Timesheet", name, {field: timesheet.get(field) for field in FIELDS}, update_modified=False
		)
