# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

"""Keeps Compliance Documents in step with the expiry dates typed on the
vehicle and employee forms.

The client wants these dates on the vehicle master and on the Employee form -
registration, mortgage end, Asateel permit, CICPA pass, driving licence, ADNOC
medical - and wants a reminder at one month, 15 days and one week. This app
already has one engine for "a document that expires and must be chased":
Compliance Document, with its status and the daily reminder job. Rather than
build a second alert path that could disagree with the first, the form field is
the **entry point** and the Compliance Document is what the alerts read. The
copy runs one way, form to document.

Two rules keep that safe:

* Saving the form **updates** the document, but only for a date that was just
  entered or changed - an unrelated save never rewrites it.
* The daily job and the first sight of an existing vehicle only **create** a
  missing document, never update one. A renewal recorded straight on the
  Compliance Document must not be rolled back to an older date still sitting on
  the form.
"""

import frappe
from frappe import _
from frappe.utils import getdate

# (expiry field on the form, Compliance Document type, number field, attachment field, issue-date field)
VEHICLE_SOURCES = (
	("registration_expiry", "Mulkiya (Registration)", None, "registration_image", "registration_date"),
	("insurance_expiry", "Insurance Policy", None, "insurance_image", None),
	("asateel_permit_expiry", "Asateel Permit", "asateel_permit_number", None, None),
	("cicpa_pass_expiry", "CICPA Pass", "cicpa_pass_number", None, None),
	("mortgage_end_date", "Vehicle Mortgage", None, None, "mortgage_start_date"),
)

EMPLOYEE_SOURCES = (
	("driver_license_expiry", "Driving License", "driver_license_number", None, "driver_license_issue_date"),
	("cicpa_pass_expiry", "CICPA Pass", "cicpa_pass_number", None, None),
	("adnoc_medical_expiry", "ADNOC Medical Report", "adnoc_medical_report_number", "adnoc_medical_report", None),
)

TRAINING_TYPE = "Training Certificate"


def upsert_compliance_document(
	attached_to_doctype,
	attached_to_name,
	document_type,
	expiry_date,
	document_number=None,
	attachment=None,
	issue_date=None,
	update=True,
):
	"""Create the Compliance Document for one expiry date, or update it.

	With `update` False an existing document is left exactly as it is. Returns
	(name, created) - (None, False) when there was no expiry date to record."""
	if not expiry_date:
		return None, False

	filters = {
		"attached_to_doctype": attached_to_doctype,
		"attached_to_name": attached_to_name,
		"document_type": document_type,
	}
	# A person can hold several training certificates; the certificate's own
	# name tells them apart. Every other type is one-per-holder.
	if document_type == TRAINING_TYPE and document_number:
		filters["document_number"] = document_number

	existing = frappe.get_all(
		"Compliance Document", filters=filters, pluck="name", order_by="expiry_date desc", limit=1
	)

	if not existing:
		doc = frappe.get_doc(
			{
				"doctype": "Compliance Document",
				**filters,
				"document_number": document_number,
				"issue_date": issue_date,
				"expiry_date": getdate(expiry_date),
				"attachment": attachment,
				"auto_synced": 1,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc.name, True

	if not update:
		return existing[0], False

	doc = frappe.get_doc("Compliance Document", existing[0])
	changed = False
	for fieldname, value in (
		("expiry_date", getdate(expiry_date)),
		("document_number", document_number),
		("attachment", attachment),
		("issue_date", issue_date),
	):
		# A source that doesn't carry this detail leaves it alone.
		if value in (None, ""):
			continue
		if doc.get(fieldname) != value:
			doc.set(fieldname, value)
			changed = True

	if not doc.auto_synced:
		doc.auto_synced = 1
		changed = True

	if changed:
		doc.save(ignore_permissions=True)

	return doc.name, False


def _sync_sources(doc, sources, doctype):
	for expiry_field, document_type, number_field, attachment_field, issue_field in sources:
		expiry = doc.get(expiry_field)
		if not expiry:
			continue

		upsert_compliance_document(
			doctype,
			doc.name,
			document_type,
			expiry,
			document_number=doc.get(number_field) if number_field else None,
			attachment=doc.get(attachment_field) if attachment_field else None,
			issue_date=doc.get(issue_field) if issue_field else None,
			update=doc.is_new() or doc.has_value_changed(expiry_field),
		)


def sync_vehicle_compliance(doc, method=None):
	"""Rental Vehicle on_update."""
	try:
		_sync_sources(doc, VEHICLE_SOURCES, "Rental Vehicle")
	except Exception:
		# The vehicle itself has saved; a failed copy must not undo that. It is
		# logged, and the daily job creates anything that is still missing.
		frappe.log_error(title="Compliance sync failed: Rental Vehicle", message=frappe.get_traceback())
		frappe.msgprint(
			_("The vehicle was saved, but its expiry dates could not be copied to Compliance Documents. "
			  "See the Error Log."),
			indicator="orange",
			alert=True,
		)


def sync_employee_compliance(doc, method=None):
	"""Employee on_update - drivers only."""
	if not doc.get("is_driver"):
		return

	try:
		_sync_sources(doc, EMPLOYEE_SOURCES, "Employee")

		for row in doc.get("driver_training_certificates") or []:
			upsert_compliance_document(
				"Employee",
				doc.name,
				TRAINING_TYPE,
				row.expiry_date,
				document_number=row.certificate_name,
				attachment=row.attachment,
				issue_date=row.issue_date,
				update=True,
			)
	except Exception:
		frappe.log_error(title="Compliance sync failed: Employee", message=frappe.get_traceback())
		frappe.msgprint(
			_("The employee was saved, but their expiry dates could not be copied to Compliance Documents. "
			  "See the Error Log."),
			indicator="orange",
			alert=True,
		)


def sync_all_expiry_sources():
	"""Create any Compliance Document the forms imply but that does not exist
	yet. Create-only (see the module docstring) - run daily ahead of the alerts,
	so vehicles and drivers entered before this was added are covered without a
	one-off migration."""
	created = 0

	vehicle_fields = {f for source in VEHICLE_SOURCES for f in source[:5] if f}
	vehicle_fields = [f for f in vehicle_fields if frappe.db.has_column("Rental Vehicle", f)]
	if vehicle_fields:
		for vehicle in frappe.get_all("Rental Vehicle", fields=["name", *vehicle_fields]):
			for expiry_field, document_type, number_field, attachment_field, issue_field in VEHICLE_SOURCES:
				if not vehicle.get(expiry_field):
					continue
				_name, made = upsert_compliance_document(
					"Rental Vehicle",
					vehicle.name,
					document_type,
					vehicle.get(expiry_field),
					document_number=vehicle.get(number_field) if number_field else None,
					attachment=vehicle.get(attachment_field) if attachment_field else None,
					issue_date=vehicle.get(issue_field) if issue_field else None,
					update=False,
				)
				created += made

	if frappe.db.has_column("Employee", "is_driver"):
		employee_fields = {f for source in EMPLOYEE_SOURCES for f in source[:5] if f}
		employee_fields = [f for f in employee_fields if frappe.db.has_column("Employee", f)]
		for employee in frappe.get_all("Employee", filters={"is_driver": 1}, fields=["name", *employee_fields]):
			for expiry_field, document_type, number_field, attachment_field, issue_field in EMPLOYEE_SOURCES:
				if not employee.get(expiry_field):
					continue
				_name, made = upsert_compliance_document(
					"Employee",
					employee.name,
					document_type,
					employee.get(expiry_field),
					document_number=employee.get(number_field) if number_field else None,
					attachment=employee.get(attachment_field) if attachment_field else None,
					issue_date=employee.get(issue_field) if issue_field else None,
					update=False,
				)
				created += made

	return created
