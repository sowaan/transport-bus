# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

"""Keeps a staged fine and the invoice raised from it agreeing with each other.

A fine carries `is_invoiced`, and an invoice carries the fine it was raised from
(`custom_traffic_fine_staging`). The flag is what the fetch path filters on in
SQL - `_stage_fine` will not enrich a row that has already been billed - so it
has to be a real column rather than something computed on read.

That leaves one thing to arrange: the flag is set when the invoice is created,
and nothing was putting it back. An invoice that is cancelled or deleted leaves
the fine unpaid and unbilled, but the fine went on claiming it had been
invoiced, so the button never came back and the fine could never be re-raised.
That is the re-creation requirement, and it is a two-sided fact - which is why
it is corrected from the invoice's own events rather than from the fine, where
nothing would ever know to look.

`on_trash` rather than `after_delete`: the row still exists here, so the link
back to the fine is still readable. After the delete it is not.
"""

import frappe

STAGING = "Traffic Fine Staging"


def refresh_fine_on_cancel(doc, method=None):
	_refresh(doc.get("custom_traffic_fine_staging"))


def refresh_fine_on_trash(doc, method=None):
	_refresh(doc.get("custom_traffic_fine_staging"), ignoring=doc.name)


def _refresh(fine, ignoring=None):
	"""Set the fine's flag to whether an invoice still stands against it.

	`ignoring` is the invoice currently being deleted. It is still in the
	database while `on_trash` runs, so counting it would leave the fine marked
	invoiced by a document that is about to stop existing.
	"""
	if not fine or not frappe.db.exists(STAGING, fine):
		return

	filters = {"custom_traffic_fine_staging": fine, "docstatus": ("!=", 2)}
	if ignoring:
		filters["name"] = ("!=", ignoring)

	invoiced = 1 if frappe.db.get_value("Purchase Invoice", filters, "name") else 0

	# Written straight to the column: saving the fine would run `after_save`,
	# which raises a Purchase Invoice - so correcting the flag after a
	# cancellation would immediately create the invoice that was just
	# cancelled. `update_modified` is left alone deliberately; a person did
	# cancel something, and the fine genuinely changed state.
	frappe.db.set_value(STAGING, fine, "is_invoiced", invoiced)
