# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

import frappe
from frappe import _

from transport.transport.doctype.vehicle_inspection.vehicle_inspection import default_check_points
from transport.transport.driver_portal import get_driver_for_user, get_inspectable_vehicles, todays_inspection

no_cache = 1


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/driver/inspection"
		raise frappe.Redirect

	context.title = _("Vehicle inspection")
	context.no_breadcrumbs = True

	driver = get_driver_for_user()
	if not driver:
		context.error = _("No Driver record is linked to your account. Contact Operations.")
		return

	context.driver_name = frappe.db.get_value("Driver", driver, "full_name") or driver
	context.points = default_check_points()
	context.vehicles = [
		{"name": vehicle, "done": todays_inspection(vehicle)} for vehicle in get_inspectable_vehicles(driver)
	]
