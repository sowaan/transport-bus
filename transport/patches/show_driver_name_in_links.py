import frappe


def execute():
	"""Show the driver's name, not HR-DRI-2026-00005, wherever a Driver is linked.

	The client's UAT note: "Driver name ... not showing in timesheet". The
	timesheet lines held the right driver, but a Link field displays the target's
	ID, and a Driver's ID is a series number. Driver already declares
	`full_name` as its title field; switching on show_title_field_in_link makes
	every Link to it - the timesheet grid, Trip, Trip Feedback, Vehicle
	Inspection - show that name instead. A Property Setter rather than an edit to
	ERPNext's own doctype file."""
	if frappe.db.get_value("Property Setter", {"doc_type": "Driver", "property": "show_title_field_in_link"}):
		return

	frappe.make_property_setter(
		{
			"doctype": "Driver",
			"doctype_or_field": "DocType",
			"property": "show_title_field_in_link",
			"value": "1",
			"property_type": "Check",
		}
	)
