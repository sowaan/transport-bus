# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

"""A published Salik / Darb tariff, kept as reference data.

Nothing here is billed from. It exists so the rates the fine-side comparison
reads are a dated, sourced record rather than a number someone remembers, and
so a tariff change is a new document (new `effective_from`) rather than an
edit that rewrites history.

Uniqueness on authority + effective_from comes from the autoname, which is
built from exactly those two fields - a second tariff for the same pair is a
duplicate-name error rather than something validate() has to police.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate


class TollTariff(Document):
	def validate(self):
		if self.effective_to and getdate(self.effective_to) < getdate(self.effective_from):
			frappe.throw(_("Effective To cannot be before Effective From."))
		self.validate_rates()

	def validate_rates(self):
		"""Times belong to tolls only.

		Frappe fills every blank Time field with the current clock time inside
		insert()/save(), before this runs (`create_new.py`: the Time branch is
		unconditional). So a penalty row that was never given a time arrives here
		carrying a fabricated one - clear it. The reverse, a Toll row whose time
		was left blank, is indistinguishable from one typed as "now" by the time
		it reaches the server; the form script catches that case for desk entry,
		and anything inserting from code must pass both times explicitly.
		"""
		for row in self.rates:
			if row.kind == "Penalty":
				row.from_time = None
				row.to_time = None
				continue
			if not row.from_time or not row.to_time:
				frappe.throw(_("Row {0}: a Toll rate needs both From and To times.").format(row.idx))
			if str(row.from_time) == str(row.to_time):
				frappe.throw(_("Row {0}: From and To times cannot be the same.").format(row.idx))
