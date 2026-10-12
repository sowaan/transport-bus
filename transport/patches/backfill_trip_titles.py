import frappe

from transport.transport.doctype.trip.trip import build_trip_title


def execute():
	"""Give every existing Trip its name ("From -> To . date . leg").

	New and re-saved Trips get it from Trip.validate(); this covers the ones that
	exist already so lists and Link pickers read the same everywhere. Written
	straight to the column - re-saving would re-run validation (double-booking,
	blacklist, Sales Order) on historical records, and would stamp them as
	modified today."""
	for trip in frappe.get_all(
		"Trip", fields=["name", "from_place", "to_place", "trip_date", "direction"]
	):
		frappe.db.set_value(
			"Trip",
			trip.name,
			"trip_title",
			build_trip_title(trip.from_place, trip.to_place, trip.trip_date, trip.direction),
			update_modified=False,
		)
