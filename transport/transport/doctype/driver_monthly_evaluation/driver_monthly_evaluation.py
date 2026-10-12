# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

"""Second, scored driver evaluation form from the client's source workflow
document: ten standard criteria worth ten points each (100 total), summed into
an overall percentage that maps onto the form's rating bands
(Excellent / Very Good / Good / Satisfactory / Needs Improvement), plus a
recommended-action checklist and evaluator/driver sign-off.

Deliberately kept separate from the existing `Driver Evaluation` doctype,
which implements a different Good/Poor multi-rater form that also appears in
the same source document - both forms are real and are used side by side.

The client's UAT note added a second scorer: the customer, on six heads out of 5
(`evaluation_type`). The heads for both live in transport.transport.evaluation_heads.

Like `Driver Evaluation`, this doctype does NOT feed `Driver.average_rating`
and does not participate in auto-blacklisting; that remains Trip Feedback's
job.
"""

import frappe
from frappe.model.document import Document

from transport.transport.evaluation_heads import (
	default_criteria,
	seed_criteria,
	validate_scores,
)

CUSTOMER = "Customer"

# (minimum percentage, label) - evaluated highest band first.
RATING_BANDS = (
	(90, "Excellent"),
	(80, "Very Good"),
	(70, "Good"),
	(60, "Satisfactory"),
	(0, "Needs Improvement"),
)


def get_rating_band(percentage):
	"""Return the form's rating label for a 0-100 percentage."""
	for minimum, label in RATING_BANDS:
		if percentage >= minimum:
			return label

	return RATING_BANDS[-1][1]


@frappe.whitelist()
def get_criteria(evaluation_type=None):
	"""The standard heads for a new form. The desk form calls this on load: the
	criteria table is `reqd`, so Frappe shows a blank row on a new document and
	the heads used to appear only after the first save."""
	return default_criteria(customer=evaluation_type == CUSTOMER)


class DriverMonthlyEvaluation(Document):
	def validate(self):
		self.seed_criteria()
		self.calculate_totals()
		self.validate_scores()

	def seed_criteria(self):
		"""Populate the standard heads on a fresh form.

		Existing rows are never wiped or reordered - an evaluation saved under
		earlier heads keeps them."""
		seed_criteria(self, "criteria", customer=self.evaluation_type == CUSTOMER)

	def validate_scores(self):
		validate_scores(self, "criteria", minimum=0)

	def calculate_totals(self):
		total = maximum = 0
		for row in self.criteria:
			total += frappe.utils.cint(row.score_given)
			maximum += frappe.utils.cint(row.max_score)

		self.total_score = total
		self.max_total_score = maximum

		percentage = (total / maximum * 100) if maximum else 0
		self.overall_rating = get_rating_band(percentage)
