// Copyright (c) 2026, Sowaan and contributors
// For license information, please see license.txt

// Trips on a calendar - month, week or day - titled by what the trip is (From to To),
// coloured by where it stands. Filter the sidebar by vehicle, driver, customer or
// project for the vehicle-wise / driver-wise / client-wise / project-wise views.
frappe.views.calendar["Trip"] = {
	field_map: {
		start: "trip_date",
		end: "trip_date",
		id: "name",
		title: "trip_title",
		allDay: "all_day",
	},
	order_by: "trip_date",
	get_css_class(data) {
		const classes = {
			Draft: "default",
			Assigned: "info",
			Accepted: "info",
			Rejected: "danger",
			Started: "warning",
			Completed: "success",
			Approved: "success",
			Cancelled: "danger",
		};
		return classes[data.status] || "default";
	},
};
