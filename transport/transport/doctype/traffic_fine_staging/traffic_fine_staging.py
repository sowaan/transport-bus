# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

"""A fine, from the portal that reported it through to the invoice that pays it.

This used to be only the landing area for a fetched row, which a person then
promoted into a separate Transport Traffic Fine. That second doctype has been
retired and everything it carried lives here, so the row a fetch writes and the
record accounting works on are the same document. Nothing has to be promoted,
and the two can no longer disagree about the same fine.

What came across, and why each piece matters:

* **Assignment** - Trip, Driver, Project, Customer, and the three-way
  `responsibility` the source document calls for. fleetify's own Traffic Fine is
  hard-wired to a Rental Agreement and expresses this as a `billed_to_customer`
  boolean; corporate trips have no agreement at all and need the three-way split.
* **VAT**, computed but off by default - see `add_vat`.
* **The black-points chain** - paying a Driver-responsibility fine opens a
  Driver Incident, which is what accumulates towards blacklisting. That loop is
  the reason this is a record with a lifecycle rather than a queue.

`raw_payload` is still kept alongside, so a bad mapping can be diagnosed later
without re-querying the portal.
"""

import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import escape_html, flt, getdate

VAT_RATE = 0.05


class TrafficFineStaging(Document):
	def validate(self):
		self.calculate_vat()
		self.check_duplicate_ticket()

	def on_update(self):
		self.apply_black_points()

	def after_save(self):
		# A patch must never raise accounting documents as a side effect of
		# touching a row. `run_patches` sets this flag for the whole run
		# (frappe/modules/patch_handler.py:233), so a migration that backfills a
		# column or merges a retired doctype in cannot silently create an
		# invoice per row - there are 59 uninvoiced rows on this bench alone.
		if frappe.flags.in_patch:
			return

		if not self.live_invoice():
			self.create_purchase_invoice()

	def live_invoice(self):
		"""The Purchase Invoice standing against this fine, if there is one.

		Asked as a question rather than read from `is_invoiced`, because the
		flag is a record of what happened once and this has to be true *now*.
		A cancelled or deleted invoice leaves the fine unpaid and un-billed, and
		the fine has to be invoiceable again - which is the whole of the
		re-creation requirement. Draft and submitted both count as standing;
		only cancelled (docstatus 2) does not.
		"""
		return frappe.db.get_value(
			"Purchase Invoice",
			{"custom_traffic_fine_staging": self.name, "docstatus": ("!=", 2)},
			"name",
		)

	def sync_invoiced_flag(self):
		"""Bring `is_invoiced` back in line with whether an invoice stands.

		Still a stored column rather than something computed on read: the fetch
		path filters on it in SQL (`_stage_fine` will not enrich a row that has
		been billed) and a property would not be there to filter on.
		"""
		invoiced = 1 if self.live_invoice() else 0
		if frappe.utils.cint(self.is_invoiced) != invoiced:
			self.db_set("is_invoiced", invoiced, update_modified=False)

	@frappe.whitelist()
	def rematch_vehicle(self):
		"""Look the plate up against the fleet again.

		`vehicle` is read-only on the form on purpose. It is our match, not the
		portal's word, and letting somebody type one in would paper over a plate
		that is wrong on the Rental Vehicle - where every future fine for that
		car will fail to match too. Correct the fleet record, then press this.
		"""
		from transport.transport.fine_sync.service import _vehicle_for_plate

		raw = self.payload()
		match = _vehicle_for_plate(
			raw.get("plate_code"), raw.get("plate_number"), raw.get("plate_emirate")
		)
		if not match:
			frappe.msgprint(
				_("No single fleet vehicle matches plate {0}. Either it is not ours, or the "
				  "plate on the Rental Vehicle does not agree with the one the portal "
				  "reported.").format(self.plate or _("(none reported)")),
				title=_("No Match"),
			)
			return None

		self.db_set("vehicle", match.name)
		frappe.msgprint(_("Matched to {0}.").format(match.name))
		return match.name

	def billing_targets(self):
		"""Who to bill and what to charge it to, read from the portal itself.

		Not `self.supplier` and `self.item`. Those are `fetch_from` fields, which
		Frappe copies out of the portal once, when the row is saved, and never
		looks at again. A fine staged before somebody configured the portal keeps
		whatever the portal held at the time - and configuring the portal
		afterwards does not reach back. Every such fine would refuse to invoice
		for ever, with a message telling you to set the very thing that is
		already set.

		That is not hypothetical, it is the third time this exact copy has been
		wrong: `supplier` once held the portal's NAME (a Link to a Supplier that
		did not exist), then `item` held the portal's name too, and then `item`
		held nothing at all because the rows were resynced while no portal had
		one. A copy taken at save time cannot answer a question asked at invoice
		time.

		The portal wins where it has a value, because it is the configured source
		and the row only ever held a snapshot of it. The row is the fallback, so
		a hand-entered fine that belongs to no portal can still name its own.
		"""
		portal = (
			frappe.db.get_value(
				"Traffic Fine Portal", self.portal, ["supplier", "item"], as_dict=True
			)
			if self.portal
			else None
		) or frappe._dict()

		return (portal.supplier or self.supplier), (portal.item or self.item)

	def payload(self):
		"""`raw_payload` as a dict, for anything that has to read what the portal
		sent. Never raises: a hand-entered fine has no payload at all, and
		`_stage_fine` truncates what it stores at 10000 characters, which writes
		a large enough row as invalid JSON. Neither is worth failing a save for.
		"""
		if not self.raw_payload:
			return {}
		try:
			return json.loads(self.raw_payload) or {}
		except ValueError:
			return {}

	def check_duplicate_ticket(self):
		"""A ticket number identifies a fine, but only within the authority that
		issued it - two emirates can legitimately issue the same number. The
		identity of a fine is therefore (portal, ticket number).

		Enforced here rather than by a database unique index on purpose: Frappe
		stores an empty Data field as '' rather than NULL, so a unique index
		would treat every blank ticket number as a collision and block a second
		hand-entered fine that has not been given one yet.

		`_stage_fine` looks the same pair up before inserting, which is what
		makes re-running a sync idempotent. This is the backstop for the rows a
		person creates or edits by hand, where nothing has looked first.
		"""
		if not self.ticket_number:
			return

		portal_val = self.portal if self.portal else ["in", ["", None]]
		duplicate = frappe.db.exists(
			"Traffic Fine Staging",
			{
				"ticket_number": self.ticket_number,
				"portal": portal_val,
				"name": ["!=", self.name or ""],
			},
		)
		if duplicate:
			frappe.throw(
				_("Ticket {0} is already recorded on {1}{2}.").format(
					self.ticket_number,
					duplicate,
					_(" for the same portal") if self.portal else "",
				),
				title=_("Duplicate Fine"),
			)

	def calculate_vat(self):
		self.vat_amount = flt(self.amount) * VAT_RATE if self.add_vat else 0
		self.total_cost = flt(self.amount) + flt(self.vat_amount)

	def apply_black_points(self):
		if self.black_points_on_hold:
			# Fetched fines arrive already marked Paid by some portals. Without
			# this hold, importing a driver's fine history would satisfy the
			# condition below on the very first save and blacklist them
			# retroactively for fines settled long ago. A person clears the hold
			# once they have confirmed the driver is genuinely responsible.
			return
		if self.black_points_applied or self.responsibility != "Driver" or self.status != "Paid":
			return
		if not self.driver:
			return

		# The authority's own count wins when we have it. The Transport Settings
		# figure is a flat default for hand-entered fines, and applying it to a
		# fetched one would record a 12-point violation as a 2-point one -
		# understating exactly the fines that matter most for blacklisting.
		points = self.black_points or frappe.db.get_single_value(
			"Transport Settings", "black_points_per_fine"
		) or 0
		incident = frappe.get_doc(
			{
				"doctype": "Driver Incident",
				"driver": self.driver,
				"trip": self.trip,
				"incident_type": "Traffic Fine",
				"description": _("Traffic Fine {0} ({1}) - {2}").format(
					self.ticket_number or self.name, self.fine_type or "", self.name
				),
				"black_points": points,
				"source_traffic_fine": self.name,
			}
		)
		incident.insert(ignore_permissions=True)

		self.db_set({"black_points_applied": 1, "driver_incident": incident.name})

	@frappe.whitelist()
	def create_purchase_invoice(self):
		"""Raise the Draft invoice that pays this fine.

		Re-runnable by design. The guard is "is there an invoice standing
		against this fine right now", not "was one ever made" - so an invoice
		that was cancelled or deleted leaves the fine billable again, while one
		that is merely still in Draft does not produce a second.
		"""
		standing = self.live_invoice()
		if standing:
			frappe.throw(
				_("Purchase Invoice {0} already stands against this fine. Cancel or delete it "
				  "before raising another.").format(standing),
				title=_("Already Invoiced"),
			)

		if not self.amount:
			frappe.throw(_("Fine amount is missing."), title=_("Nothing to Invoice"))

		supplier, item = self.billing_targets()

		if not supplier:
			frappe.throw(
				_("{0} has no supplier, so there is nobody to raise this invoice against. Set "
				  "one on the portal.").format(self.portal or _("This fine")),
				title=_("Supplier Missing"),
			)

		if not item:
			frappe.throw(
				_("{0} has no item, so the invoice has nothing to charge against. Set one on "
				  "the portal.").format(self.portal or _("This fine")),
				title=_("Item Missing"),
			)

		invoice = frappe.get_doc({
			"doctype": "Purchase Invoice",
			"supplier": supplier,
			# The fine, as a link. Every other portal detail on the invoice
			# fetches through this one field, so the invoice cannot end up
			# disagreeing with the fine it was raised from.
			"custom_traffic_fine_staging": self.name,
			# `bill_no` is "Supplier Invoice No" - the reference the SUPPLIER put
			# on their own document. For a fine that is the authority's ticket or
			# fine number, so that is what goes here. It used to hold our staging
			# id, which was both the wrong value for the field and the only
			# record of the connection; the connection is the link above now, and
			# this field goes back to meaning what ERPNext says it means.
			#
			# It is also mandatory on this site (a Property Setter sets reqd),
			# so leaving it empty is not available even if it were tidier.
			"bill_no": self.ticket_number,
			"bill_date": getdate(self.fine_datetime) if self.fine_datetime else None,
			"items": [
				{
					"item_code": item,
					"qty": 1,
					"rate": self.amount,
					# Why the fine was issued, and nothing else. Everything that
					# used to be crammed in here - ticket number, plate, type,
					# authority - now has a field of its own on the invoice,
					# where it can be filtered, reported on and reconciled
					# instead of read out of a sentence.
					"description": escape_html(self.description or self.fine_type or ""),
				}
			],
		})

		self.apply_portal_discount(invoice)
		invoice.insert()

		# The stored copies are what the form shows, so bring them back in line
		# with what was actually billed rather than leaving a blank field beside
		# an invoice that plainly found one.
		self.db_set({"is_invoiced": 1, "supplier": supplier, "item": item})
		frappe.msgprint(
			_("Purchase Invoice {0} created.").format(invoice.name), alert=True
		)
		return invoice.name

	def apply_portal_discount(self, invoice):
		"""Carry the authority's early-payment discount onto the invoice.

		`discounted_amount` is what the authority will accept, not the amount
		taken off, so the discount is the difference. Applied on Grand Total
		because that is what the portal discounts - the figure on the page is
		the whole payable, not a line adjustment.

		The offer is time-limited and the window is published as prose ("35% if
		paid within 58 days"), with no structured expiry to check against. The
		discount is applied because the requirement asks for it, and
		`discount_note` is carried onto the invoice beside it so whoever pays is
		looking at the deadline rather than trusting a number that may already
		have lapsed.
		"""
		discounted = flt(self.discounted_amount)
		if not discounted or discounted >= flt(self.amount):
			return

		invoice.apply_discount_on = "Grand Total"
		invoice.discount_amount = flt(self.amount) - discounted
