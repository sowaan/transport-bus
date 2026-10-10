# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

"""One toll gate crossing read from a toll authority's customer portal.

A charge, not a fine: it is deliberately a separate doctype from Traffic Fine
Staging, which raises a Purchase Invoice on save. This one has no side
effects at all - no validate, no invoicing, not submittable - and is written
only by the portal ingest.

The name is built from authority + transaction_id, so reading the same
crossing twice is a duplicate-name error rather than a second row.
"""

from frappe.model.document import Document


class TollCrossing(Document):
	pass
