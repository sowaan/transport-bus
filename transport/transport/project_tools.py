# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

"""Tools that turn what a Project says into the records Operations plans from."""

import re

import frappe
from frappe import _

_CLOCK = re.compile(r"^\s*(\d{1,2})(?:[:.](\d{2}))?\s*([AaPp])?\.?[Mm]?\.?\s*$")


def parse_clock(text):
	"""'6.00 AM', '5:30pm', '17.30', '6 am' -> '06:00:00'; None if it isn't a
	time. The project sheet is typed by hand, so every one of those occurs."""
	match = _CLOCK.match(text or "")
	if not match:
		return None

	hour, minute, meridiem = int(match.group(1)), int(match.group(2) or 0), match.group(3)
	if meridiem:
		if not 1 <= hour <= 12:
			return None
		hour = hour % 12 + (12 if meridiem.lower() == "p" else 0)
	if hour > 23 or minute > 59:
		return None

	return f"{hour:02d}:{minute:02d}:00"


@frappe.whitelist()
def create_routes_from_shifts(project):
	"""One Route per shift on the Project's contract terms, so trip planning can
	start from what the contract already says.

	The UAT note: "Its better if the route is created from the Sales order /
	Project so that the trip related details will be automatically filled." A
	shift becomes a Route when it names both places and has pickup and drop
	times that read as times; a Route that already joins the same two places on
	this Project is left alone. Everything skipped is reported with its reason."""
	frappe.has_permission("Route", "create", throw=True)
	doc = frappe.get_doc("Project", project)
	doc.check_permission("read")

	created, skipped = [], []
	for row in doc.get("transport_shifts") or []:
		label = row.shift
		if not (row.from_place and row.to_place):
			skipped.append(_("{0}: set the From and To places on the shift").format(label))
			continue

		pickup, drop = parse_clock(row.pickup_time), parse_clock(row.drop_time)
		if not (pickup and drop):
			skipped.append(_("{0}: the pickup / drop times are missing or are not times (use e.g. 6.00 AM)").format(label))
			continue

		existing = frappe.db.exists(
			"Route", {"project": project, "from_place": row.from_place, "to_place": row.to_place}
		)
		if existing:
			skipped.append(_("{0}: Route {1} already joins these places").format(label, existing))
			continue

		route = frappe.get_doc(
			{
				"doctype": "Route",
				"route_name": f"{row.from_place} to {row.to_place} ({row.shift})",
				"project": project,
				"from_place": row.from_place,
				"to_place": row.to_place,
				"pickup_time": pickup,
				"drop_time": drop,
				"vehicle_category": row.vehicle_category or "",
				"is_active": 1,
			}
		).insert()
		created.append(route.name)

	return {"created": created, "skipped": skipped}


def sync_project_from_sales_order(doc, method=None):
	"""Sales Order on_submit: carry what the order already says onto its Project.

	The UAT note: "All details related to the trip should automatically fill the
	Project doctype to avoid double work." Fills **only what the Project has
	blank** - a Project someone has already set up is never overwritten - and only
	for a transport order: Sales Order is shared with the group's other companies.

	What it carries: locations, start and end dates, the customer and the order
	itself, and the vehicles named on the order's lines together with the driver
	normally allocated to each."""
	project_name = doc.get("project") or doc.get("transport_project")
	if not (doc.get("transport_project") and project_name and frappe.db.exists("Project", project_name)):
		return

	project = frappe.get_doc("Project", project_name)
	changed = False

	for fieldname, value in (
		("transport_locations", doc.get("transport_locations")),
		("expected_start_date", doc.get("transport_start_date")),
		("expected_end_date", doc.get("transport_end_date")),
		("customer", doc.customer),
		("sales_order", doc.name),
	):
		if value and not project.get(fieldname):
			project.set(fieldname, value)
			changed = True

	present = {row.vehicle for row in project.get("transport_vehicles") or []}
	for item in doc.get("items") or []:
		vehicle = item.get("transport_vehicle")
		if vehicle and vehicle not in present:
			project.append(
				"transport_vehicles",
				{"vehicle": vehicle, "driver": frappe.db.get_value("Rental Vehicle", vehicle, "assigned_driver")},
			)
			present.add(vehicle)
			changed = True

	if changed:
		project.flags.ignore_permissions = True
		project.save()
