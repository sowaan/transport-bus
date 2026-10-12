# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

"""A training certificate held by a driver, listed on the Employee form.

Each row with an expiry date is mirrored into a Compliance Document (type
"Training Certificate") by transport.transport.compliance_sync, so the one alert
engine covers it."""

from frappe.model.document import Document


class DriverTrainingCertificate(Document):
	pass
