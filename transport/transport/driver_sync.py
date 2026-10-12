# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

"""An Employee marked Is Driver gets a Driver record, kept in step with the form.

The client's UAT note: "Option to mark the employee as Driver and to fill the
required field at the time of Employee creation itself." Drivers are not a
separate hire - they are employees - so the Employee form carries the driver
details and this keeps the Driver document (the one a Trip, a fine or an
evaluation points at) from being a second place to type the same licence.

The Driver is created the first time the employee is saved as a driver, and
afterwards only the fields the Employee form owns are copied across - the
licence, the licence class and the phone. Everything else on the Driver
(transporter, blacklist, rating, black points) is left alone."""

import frappe
from frappe import _

REQUIRED_WHEN_DRIVER = (
	("driver_license_number", "Driving License Number"),
	("driver_license_type", "License Type (LMV / HMV)"),
	("driver_license_expiry", "License Expiry Date"),
)

DRIVER_STATUS = {"Active": "Active", "Inactive": "Suspended", "Suspended": "Suspended", "Left": "Left"}


def validate_driver_details(doc, method=None):
	"""Employee validate: a driver needs a licence on file."""
	if not doc.get("is_driver"):
		return

	missing = [label for fieldname, label in REQUIRED_WHEN_DRIVER if not doc.get(fieldname)]
	if missing:
		frappe.throw(
			_("An employee marked as a driver needs: {0}.").format(", ".join(_(label) for label in missing)),
			title=_("Driver details missing"),
		)


def sync_driver_from_employee(doc, method=None):
	"""Employee on_update: create or refresh the linked Driver."""
	if not doc.get("is_driver"):
		return

	values = {
		"full_name": doc.employee_name,
		"cell_number": doc.get("cell_number"),
		"license_number": doc.get("driver_license_number"),
		"issuing_date": doc.get("driver_license_issue_date"),
		"expiry_date": doc.get("driver_license_expiry"),
		"transport_license_type": doc.get("driver_license_type"),
	}

	driver_name = frappe.db.get_value("Driver", {"employee": doc.name})
	if not driver_name:
		driver = frappe.get_doc(
			{
				"doctype": "Driver",
				"employee": doc.name,
				"status": DRIVER_STATUS.get(doc.status, "Active"),
				**{k: v for k, v in values.items() if v},
			}
		)
		driver.insert(ignore_permissions=True)
		frappe.msgprint(
			_("Driver {0} created for this employee.").format(driver.name), indicator="green", alert=True
		)
		return

	driver = frappe.get_doc("Driver", driver_name)
	changed = False
	for fieldname, value in values.items():
		# Only copy what the form actually holds - a blank on the Employee form
		# must not erase a licence typed on the Driver.
		if value and driver.get(fieldname) != value:
			driver.set(fieldname, value)
			changed = True

	status = DRIVER_STATUS.get(doc.status)
	if status and driver.status != status:
		driver.status = status
		changed = True

	if changed:
		driver.save(ignore_permissions=True)
