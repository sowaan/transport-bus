# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

"""Derived values on the Rental Vehicle master (fleetify's doctype, extended
here by Custom Field fixtures - see hooks.py)."""

from frappe.utils import flt


def set_total_renewal_fee(doc, method=None):
	"""Rental Vehicle validate. The client's company vehicle list shows the three
	renewal costs and their total on one line."""
	doc.total_renewal_fee = (
		flt(doc.get("mulkiya_renewal_fee")) + flt(doc.get("insurance_renewal_fee")) + flt(doc.get("passing_fee"))
	)
