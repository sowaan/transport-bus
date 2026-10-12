# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

"""Post-trip feedback from Customer/In-Charge/Admin-HR (doc section 15) -
recorded by Operations on the source's behalf (no live Customer Portal yet,
see [[project_transport_app]]'s Phase 4 scoping note on customer approval).
A low Overall Rating auto-escalates to management, and Driver.average_rating
rolls up every Trip Feedback ever recorded against that driver, feeding
"future trip allocation" per the doc.

Scoring. The client's UAT note replaced the six fixed 1-5 fields with two forms
chosen by who is scoring: Customer (six heads out of 5) and Supervisor / Admin
(ten heads out of 10). They are rows in `criteria`, seeded from
transport.transport.evaluation_heads, and Overall Rating is still expressed out
of 5 whichever form was used - so the escalation threshold and
Driver.average_rating mean what they always did. Records saved before the change
keep their six fields and are scored the old way; nothing is migrated."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, now_datetime

from transport.transport.evaluation_heads import (
	CUSTOMER_SOURCES,
	default_criteria,
	seed_criteria,
	validate_scores,
)

RATING_FIELDS = (
	"driver_behaviour",
	"driving_quality",
	"vehicle_condition",
	"vehicle_cleanliness",
	"driver_hygiene",
	"timing_punctuality",
)


@frappe.whitelist()
def get_criteria(feedback_from=None):
	"""The heads for a new form, for the desk to fill in as it opens."""
	return default_criteria(customer=feedback_from in CUSTOMER_SOURCES)


class TripFeedback(Document):
	def validate(self):
		if self.uses_legacy_fields():
			self.validate_rating_range()
			self.calculate_overall_rating()
		else:
			seed_criteria(self, "criteria", customer=self.feedback_from in CUSTOMER_SOURCES)
			self.calculate_from_criteria()
		self.check_escalation()

	def uses_legacy_fields(self):
		"""True for a record scored on the six fixed fields - an old record, or
		an API caller that still posts them without any criteria rows."""
		return not self.criteria and any(cint(self.get(f)) for f in RATING_FIELDS)

	def validate_rating_range(self):
		for fieldname in RATING_FIELDS:
			value = self.get(fieldname)
			if value is not None and not (1 <= value <= 5):
				frappe.throw(_("{0} must be between 1 and 5.").format(self.meta.get_label(fieldname)))

	def calculate_overall_rating(self):
		values = [flt(self.get(f)) for f in RATING_FIELDS]
		self.overall_rating = sum(values) / len(values) if values else 0

	def calculate_from_criteria(self):
		total, maximum = validate_scores(self, "criteria", minimum=1, require_all=True)
		self.total_score = total
		self.max_total_score = maximum
		self.percentage = (total / maximum * 100) if maximum else 0
		# Always out of 5 - see the module docstring.
		self.overall_rating = (total / maximum * 5) if maximum else 0

	def check_escalation(self):
		if self.escalated:
			return

		threshold = frappe.db.get_single_value("Transport Settings", "feedback_escalation_rating") or 2.5
		if self.overall_rating < threshold:
			self.escalated = 1
			self.escalated_on = now_datetime()

	def on_update(self):
		before = self.get_doc_before_save()
		if self.escalated and not (before and before.escalated):
			self.notify_escalation()
		self.recalculate_driver_rating()

	def notify_escalation(self):
		from transport.transport.driver_portal import notify_roles

		notify_roles(
			("Transport Operations", "Transport In-Charge"),
			_("Low Trip Feedback - {0}").format(self.trip),
			_("Trip {0} received an Overall Rating of {1}/5 from {2}, below the escalation threshold.").format(
				self.trip, self.overall_rating, self.feedback_from
			),
			"Trip Feedback",
			self.name,
		)

	def recalculate_driver_rating(self):
		if not self.driver:
			return

		ratings = frappe.get_all("Trip Feedback", filters={"driver": self.driver}, pluck="overall_rating")
		average = sum(ratings) / len(ratings) if ratings else 0
		frappe.db.set_value("Driver", self.driver, "average_rating", average)
