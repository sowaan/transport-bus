"""`source` now names the authority that issued the fine, not how the row arrived.

It used to be a Select of `Manual` / `Portal Sync`, which duplicated something
the row already says: a fetched row is one with a `raw_payload`, because that
column only holds anything when a portal answered. The field now carries the
issuing authority instead - "Dubai Police", "Abu Dhabi", "RAK Transport
Authority" - which is what a Purchase Invoice has to name and what nothing else
on the document records. The portal is not a substitute: TAMM reports Abu Dhabi
Police fines and RTA reports Dubai Police ones, so the portal a row was read
from and the authority being paid are different facts.

Every fetcher has been writing the authority into `raw["issuing_authority"]`
all along, so the payload each row already holds is enough to backfill from -
nothing has to be re-queried.

A row whose payload does not name an authority is left blank rather than kept
as "Portal Sync". Under the new meaning that string is not an unknown value,
it is a wrong one, and it would read on an invoice as the name of the
authority.
"""

import json

import frappe


def execute():
	rows = frappe.db.sql(
		"""select name, raw_payload from `tabTraffic Fine Staging`
			where coalesce(source, '') in ('Manual', 'Portal Sync')""",
		as_dict=True,
	)
	for row in rows:
		authority = _authority(row.raw_payload)
		frappe.db.set_value(
			"Traffic Fine Staging",
			row.name,
			"source",
			authority,
			# A backfill is not somebody touching the fine. Moving `modified`
			# would put every one of these rows at the top of the list view's
			# "Last Updated On", which is what an operator reads to find the
			# rows a sync just brought in.
			update_modified=False,
		)


def _authority(payload):
	"""The authority named in a payload, or "" for a row that has none.

	Tolerant of a payload that will not parse: `_stage_fine` truncates the JSON
	it stores at 10000 characters, so a large enough row is written as invalid
	JSON. That is a row we cannot read an authority out of, which is the same
	outcome as a row that never named one - and not a reason to fail a patch
	that has already corrected everything before it.
	"""
	if not payload:
		return ""
	try:
		return (json.loads(payload) or {}).get("issuing_authority") or ""
	except ValueError:
		return ""
