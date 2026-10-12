# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

"""The scored heads of the client's two evaluation forms, in one place.

The client's UAT note replaced the heads on both Trip Feedback and Driver
Monthly Evaluation with two fixed lists, depending on who is scoring:

* Supervisor / Admin - ten heads, each out of 10 (the Driver's Monthly
  Evaluation Form).
* Customer - six heads, each out of 5.

Both doctypes seed their criteria table from here, so a change to a head is
made once. Seeding never touches rows that already exist - an evaluation saved
under earlier heads keeps them."""

import frappe
from frappe import _

SUPERVISOR_MAX_SCORE = 10
SUPERVISOR_HEADS = (
	"Attendance & Punctuality",
	"Compliance with Traffic Rules",
	"Driving Skills & Safety",
	"Vehicle Maintenance & Cleanliness",
	"Route Planning & Time Management",
	"Customer/Client Interaction & Feed back",
	"Vehicle Pre- and Post-Trip Inspection",
	"Fuel Efficiency & Cost Awareness",
	"Incident/Accident Record",
	"Following a supervisor assigned duties",
)

CUSTOMER_MAX_SCORE = 5
CUSTOMER_HEADS = (
	"Ontime Pickup & Drop Off",
	"Communication/Behavior to Staff",
	"Was the driver punctual?",
	"How was the cleanliness and condition of the vehicle?",
	"How safe and comfortable did you feel during the journey?",
	"How would you rate the driver's overall service?",
)

# Trip Feedback.feedback_from values that score with the customer's form.
CUSTOMER_SOURCES = ("Customer",)


def get_heads(customer=False):
	"""(heads, max score per head) for the form the scorer fills in."""
	if customer:
		return CUSTOMER_HEADS, CUSTOMER_MAX_SCORE
	return SUPERVISOR_HEADS, SUPERVISOR_MAX_SCORE


def default_criteria(customer=False):
	heads, max_score = get_heads(customer)
	return [{"criterion": head, "max_score": max_score} for head in heads]


def seed_criteria(doc, table_field="criteria", customer=False):
	"""Fill an empty criteria table with the standard heads. Existing rows are
	never wiped or reordered."""
	if doc.get(table_field):
		return

	for row in default_criteria(customer):
		doc.append(table_field, row)


def validate_scores(doc, table_field="criteria", minimum=0, require_all=False):
	"""Every score within 0..max (or 1..max for Trip Feedback). Returns
	(total, maximum). With require_all, a head left unscored is an error -
	a total over half-filled heads would read as a low rating."""
	total = maximum = 0
	for row in doc.get(table_field) or []:
		given = row.score_given
		unscored = given in (None, "")
		if unscored and require_all:
			frappe.throw(_("Row {0}: give a score for {1}.").format(row.idx, row.criterion))
		if not unscored:
			value = frappe.utils.cint(given)
			if value < minimum or value > frappe.utils.cint(row.max_score):
				frappe.throw(
					_("Row {0}: Score Given for {1} must be between {2} and {3}.").format(
						row.idx, row.criterion, minimum, row.max_score
					)
				)
			total += value
		maximum += frappe.utils.cint(row.max_score)
	return total, maximum
