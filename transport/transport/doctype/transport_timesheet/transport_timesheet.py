# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

"""The billing-ready record behind the client-facing monthly timesheet
(the Transport Monthly Timesheet report is the printable view of the same
data). Only Approved trips (see transport.transport.operations.approve_trip)
can be pulled in, and a trip pulled onto one Timesheet is locked
(Trip.timesheet) so it can never be double-billed onto another.

Customer approval here is modelled as recording a signed copy that came back
by email, not a live no-login web link - the source doc's "send via link"
line is a real Customer Portal (trip tracking, invoice download, raise
requests), which is explicitly a later, separate deliverable, not this
Timesheet's job. Don't build a public approval link here without revisiting
that split."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import date_diff, flt, formatdate, getdate, today

from transport.transport.utils import PUBLIC_HOLIDAY, WEEKEND, get_project_holiday_kind

def format_date_short(value):
	"""e.g. "1 Aug" - the reference invoices write dates this way in the line
	description, and the full ISO date makes a three-vehicle line unreadable."""
	return formatdate(value, "d MMM") if value else ""


OPERATIONS_ROLES = ("Transport Operations", "System Manager")
ACCOUNTS_ROLES = ("Transport Accounts", "System Manager")


class TransportTimesheet(Document):
	def validate(self):
		if self.period_to and getdate(self.period_to) < getdate(self.period_from):
			frappe.throw(_("Period To cannot be before Period From."))
		self.calculate_totals()
		self.calculate_vehicle_deployments()
		self.set_fleet_summary()
		self.push_manual_edits_to_trips()

	def push_manual_edits_to_trips(self):
		"""Source doc, Timesheet section: "Manual edits only for driver/vehicle
		changes." Those two columns are the only editable ones on the child
		table, but editing them there would otherwise be cosmetic - the real
		Trip record would keep the old driver/vehicle, so the Trip Sheet, OT
		report and P&L would all still show what was originally assigned.
		Only while Draft: once the timesheet is approved or invoiced, its lines
		are the billing record and must not be rewritten."""
		if self.status != "Draft" or self.is_new():
			return

		for row in self.trips:
			if not row.trip:
				continue

			current = frappe.db.get_value("Trip", row.trip, ["driver", "vehicle"], as_dict=True)
			if not current:
				continue

			changes = {}
			if row.driver and row.driver != current.driver:
				changes["driver"] = row.driver
			if row.vehicle and row.vehicle != current.vehicle:
				changes["vehicle"] = row.vehicle

			if changes:
				frappe.db.set_value("Trip", row.trip, changes)

	def calculate_totals(self):
		self.total_trips = len(self.trips)
		self.total_duty_trips = sum(1 for t in self.trips if t.duty_type == "Duty")
		self.total_ot_trips = sum(1 for t in self.trips if t.duty_type == "OT")
		self.total_additional_trips = sum(1 for t in self.trips if t.is_additional)
		self.total_hours = sum(flt(t.duration) for t in self.trips)

		# A round trip is a pickup and its drop. Counted as the larger of the two
		# so a lone extra leg doesn't hide a trip - this is what the "below 10
		# round trips bills per trip" rule reads.
		pickups = sum(1 for t in self.trips if t.direction == "Pickup")
		drops = sum(1 for t in self.trips if t.direction == "Drop")
		self.total_round_trips = max(pickups, drops)

		# Both counts are kept because the charge basis is configurable: a rate
		# quoted against a shift reads as per-day, but the client may confirm
		# per-trip. Accounts can also see both before approving the invoice.
		weekend_rows = [t for t in self.trips if t.holiday_type == WEEKEND]
		holiday_rows = [t for t in self.trips if t.holiday_type == PUBLIC_HOLIDAY]

		self.total_weekend_trips = len(weekend_rows)
		self.total_public_holiday_trips = len(holiday_rows)
		self.total_weekend_days = len({t.trip_date for t in weekend_rows})
		self.total_public_holiday_days = len({t.trip_date for t in holiday_rows})
		# Saturdays and Sundays are counted by the calendar, apart from the
		# holiday list: the client's timesheet wants "Saturdays" and "Sundays" as
		# their own totals, and a project with no holiday list still has both.
		self.total_saturday_trips = sum(1 for t in self.trips if t.trip_date and getdate(t.trip_date).weekday() == 5)
		self.total_sunday_trips = sum(1 for t in self.trips if t.trip_date and getdate(t.trip_date).weekday() == 6)
		self.total_weekend_hours = sum(flt(t.duration) for t in weekend_rows)
		self.total_public_holiday_hours = sum(flt(t.duration) for t in holiday_rows)
		self.total_duty_hours = sum(flt(t.duration) for t in self.trips if t.duty_type == "Duty")
		self.total_ot_hours = sum(flt(t.duration) for t in self.trips if t.duty_type == "OT")

	def set_fleet_summary(self):
		"""Who drove what, spelled out on the timesheet itself.

		The trip lines carry the Driver and Vehicle as links, which show an ID;
		the client's timesheet format opens with the driver's name and the
		vehicle type, so both are summarised here and printed from here."""
		driver_ids = list(dict.fromkeys(row.driver for row in self.trips if row.driver))
		vehicle_ids = list(dict.fromkeys(
			[row.vehicle for row in self.trips if row.vehicle]
			+ [row.vehicle for row in (self.get("monthly_deployments") or []) if row.vehicle]
		))

		names = {}
		if driver_ids:
			names = dict(frappe.get_all(
				"Driver", filters={"name": ("in", driver_ids)}, fields=["name", "full_name"], as_list=True
			))
		self.driver_names = ", ".join(names.get(driver) or driver for driver in driver_ids)

		details = {}
		if vehicle_ids:
			details = {
				v.name: v for v in frappe.get_all(
					"Rental Vehicle",
					filters={"name": ("in", vehicle_ids)},
					fields=["name", "vehicle_type", "seating_capacity"],
				)
			}
		lines = []
		for vehicle in vehicle_ids:
			info = details.get(vehicle)
			extras = []
			if info and info.seating_capacity:
				extras.append(_("{0}-seater").format(info.seating_capacity))
			if info and info.vehicle_type:
				extras.append(info.vehicle_type)
			lines.append(f"{vehicle} - {' '.join(extras)}" if extras else vehicle)
		self.vehicle_details = "\n".join(lines)

	def calculate_vehicle_deployments(self):
		"""Fill the derived columns on the Vehicle Deployment table.

		A child DocType's own validate() is never called by Frappe - nothing
		runs it - so the parent has to do this, the same way calculate_totals()
		reaches into self.trips.

		Days and KM Run are genuinely per row. Extra KM is not: the allowance is
		**per contract line per month** (6,000 km on PO 9586), and a vehicle
		swapped mid-month does not earn a second allowance. So the excess is
		worked out across every row of a Sales Order line and parked on that
		line's last row - the one whose To Date closes the month. The other rows
		of the same line read zero, which is why the column can look lopsided on
		a month with a swap. Summing the column still gives the right total."""
		if self.billing_basis != "Monthly per Vehicle":
			return

		by_line = {}
		for row in self.monthly_deployments:
			if row.from_date and row.to_date:
				if getdate(row.to_date) < getdate(row.from_date):
					frappe.throw(
						_("Row #{0}: To Date cannot be before From Date.").format(row.idx)
					)
				row.days = date_diff(row.to_date, row.from_date) + 1
			else:
				row.days = 0

			# Odometers are optional: a rental without a driver may never have a
			# reading taken. Absent readings mean "no distance claimed", never a
			# negative that would credit the customer kilometres.
			row.km_run = max(0.0, flt(row.end_odometer) - flt(row.start_odometer))
			row.extra_km_run = 0
			if row.sales_order_item:
				by_line.setdefault(row.sales_order_item, []).append(row)

		if not by_line:
			return

		allowances = dict(
			frappe.get_all(
				"Sales Order Item",
				filters={"name": ("in", list(by_line))},
				fields=["name", "transport_km_allowance"],
				as_list=True,
			)
		)

		for so_detail, rows in by_line.items():
			allowance = flt(allowances.get(so_detail))
			if not allowance:
				# No allowance on the contract line means kilometres are not
				# metered at all - never treat that as "allowance of zero", which
				# would bill every kilometre driven as excess.
				continue
			excess = sum(flt(r.km_run) for r in rows) - allowance
			if excess > 0:
				rows[-1].extra_km_run = excess

	def on_trash(self):
		if self.status != "Draft":
			frappe.throw(_("Only a Draft Timesheet can be deleted."))
		self.release_trips()

	def release_trips(self):
		for row in self.trips:
			frappe.db.set_value("Trip", row.trip, "timesheet", None)

	@frappe.whitelist()
	def populate_trips(self):
		self.check_permission("write")
		return self._populate_trips()

	def _populate_trips(self, ignore_permissions=False):
		"""`ignore_permissions` is for the timesheet built automatically when an
		In-charge approves a trip - they may approve trips but have read-only
		access to Timesheets, and approving must not fail on that."""
		if self.status != "Draft":
			frappe.throw(_("Trips can only be (re)generated while the Timesheet is Draft."))
		if not (self.project and self.period_from and self.period_to):
			frappe.throw(_("Set Project, Period From and Period To first."))

		self.set_sales_order()

		# Release any trips already locked to THIS timesheet before requerying,
		# so calling populate_trips() again (e.g. after a trip's project data
		# changed) is idempotent instead of finding zero unlocked trips left -
		# without this a second click would silently wipe the trips already
		# pulled, since they'd no longer look "unlocked" to the query below.
		self.release_trips()

		trips = frappe.get_all(
			"Trip",
			filters={
				"project": self.project,
				"trip_date": ("between", [self.period_from, self.period_to]),
				"status": "Approved",
				"timesheet": ("in", ("", None)),
			},
			fields=[
				"name", "trip_date", "route", "direction", "driver", "vehicle", "duration",
				"scheduled_time", "actual_start_time", "actual_end_time", "duty_type", "is_additional",
			],
			order_by="trip_date, scheduled_time",
		)

		self.set("trips", [])
		for trip in trips:
			holiday_kind = get_project_holiday_kind(self.project, trip.trip_date)
			self.append("trips", {
				"trip": trip.name,
				"trip_date": trip.trip_date,
				"route": trip.route,
				"direction": trip.direction,
				"driver": trip.driver,
				"vehicle": trip.vehicle,
				"scheduled_time": trip.scheduled_time,
				"actual_start_time": trip.actual_start_time,
				"actual_end_time": trip.actual_end_time,
				"duty_type": trip.duty_type,
				"is_additional": trip.is_additional,
				"is_holiday": bool(holiday_kind),
				"holiday_type": holiday_kind,
				"duration": trip.duration,
			})

		if ignore_permissions:
			self.flags.ignore_permissions = True
		self.save()
		for row in self.trips:
			frappe.db.set_value("Trip", row.trip, "timesheet", self.name)

		return {"pulled": len(trips)}

	@frappe.whitelist()
	def populate_vehicle_deployments(self):
		"""Monthly-per-vehicle counterpart of populate_trips(): here the contract
		is what gets billed, not the traffic, so the rows come from the Sales
		Order rather than from Trip records. One row per contract line that names
		a vehicle, seeded with this timesheet's period - Operations then splits a
		row in two wherever a vehicle was swapped mid-month (reference invoice
		AST-21-02390 does exactly that) and fills in odometers and fuel.

		Only the link back to the Sales Order line is copied - never the rate, KM
		allowance or extra-KM rate. Those stay on the contract and are read back
		through sales_order_item when the invoice is built, so a corrected Sales
		Order can never disagree with rows already generated. Snapshotting them
		would be right on a submittable document; this one is not."""
		self.check_permission("write")
		if self.status != "Draft":
			frappe.throw(_("Vehicle Deployments can only be (re)generated while the Timesheet is Draft."))
		if self.billing_basis != "Monthly per Vehicle":
			frappe.throw(
				_("Set Project {0}'s Billing Basis to 'Monthly per Vehicle' before generating deployments.").format(
					self.project
				)
			)
		if not (self.project and self.period_from and self.period_to):
			frappe.throw(_("Set Project, Period From and Period To first."))

		self.set_sales_order()
		if not self.sales_order:
			frappe.throw(_("No submitted Sales Order found for Project {0}.").format(self.project))

		# parent is the child row's pointer back to its Sales Order; Sales Order
		# Item's own `project` field is a per-line override almost nobody fills,
		# so filtering on it would quietly return nothing.
		lines = frappe.get_all(
			"Sales Order Item",
			filters={"parent": self.sales_order, "transport_vehicle": ("is", "set")},
			fields=["name", "transport_vehicle"],
			order_by="idx",
		)
		if not lines:
			frappe.throw(
				_("No line on Sales Order {0} names a Vehicle. Set one on each contract line first.").format(
					self.sales_order
				)
			)

		# Replace rather than merge. A second click is how Operations recovers
		# from a wrong period or an amended Sales Order, and merging would strand
		# rows for contract lines that no longer exist. The cost is that
		# hand-entered odometers, fuel and swap rows go with them, which is why
		# the button confirms first. Note that Draft-only is NOT the safety net
		# here that it is for trips: all of that data entry happens while Draft.
		self.set("monthly_deployments", [])
		for line in lines:
			self.append(
				"monthly_deployments",
				{
					"sales_order_item": line.name,
					"vehicle": line.transport_vehicle,
					"from_date": self.period_from,
					"to_date": self.period_to,
				},
			)

		self.save()
		return {"pulled": len(lines)}

	def set_sales_order(self):
		if self.sales_order:
			return
		# A Project can have more than one submitted Sales Order over its life
		# (renewal/amendment) - take the most recent one rather than whichever
		# row MySQL happens to return first.
		self.sales_order = frappe.db.get_value(
			"Sales Order", {"project": self.project, "docstatus": 1}, "name", order_by="creation desc"
		)

	@frappe.whitelist()
	def approve_by_operations(self):
		if not any(role in frappe.get_roles() for role in OPERATIONS_ROLES):
			frappe.throw(_("Not permitted to approve Timesheets."), frappe.PermissionError)
		if self.status != "Draft":
			frappe.throw(_("Only a Draft Timesheet can be sent for approval."))
		# A monthly-per-vehicle contract has no trips to count - its billable
		# unit is the vehicle-month - so the "at least one row" check has to
		# look at whichever table the Billing Basis actually shows.
		if self.billing_basis == "Monthly per Vehicle":
			if not self.monthly_deployments:
				frappe.throw(_("Add at least one vehicle deployment before approving."))
		elif not self.trips:
			frappe.throw(_("Add at least one trip before approving."))

		self.db_set({
			"status": "Pending Customer Approval",
			"operations_approved_by": frappe.session.user,
			"operations_approved_on": frappe.utils.now_datetime(),
		})
		return "Pending Customer Approval"

	@frappe.whitelist()
	def record_customer_approval(self, approved_by, attachment=None):
		if not any(role in frappe.get_roles() for role in OPERATIONS_ROLES):
			frappe.throw(_("Not permitted to record customer approval."), frappe.PermissionError)
		if self.status != "Pending Customer Approval":
			frappe.throw(_("Timesheet must be Pending Customer Approval first."))
		if not approved_by:
			frappe.throw(_("Enter the customer-side signatory's name."))

		self.db_set({
			"status": "Customer Approved",
			"customer_approved_by": approved_by,
			"customer_approved_on": today(),
			"customer_approval_attachment": attachment,
		})
		return "Customer Approved"

	def add_weekend_holiday_charges(self, invoice):
		"""The client's project contract sheet prices weekend and public-holiday
		duty separately from the monthly rate (e.g. AED 310 weekend / AED 400
		public holiday), so those days are billed on top of the Sales Order
		line rather than being absorbed into it.

		Rates live on the Project because they are per-contract. Nothing is
		added when a rate is zero/unset, when the toggle is off, or when the
		charge item is not configured - a missing rate must never silently
		invoice as 0, and a missing item would otherwise throw mid-invoice."""
		settings = frappe.get_single("Transport Settings")
		if not settings.auto_bill_weekend_holiday:
			return

		per_day = (settings.weekend_holiday_charge_basis or "Per Day") == "Per Day"
		project = frappe.db.get_value(
			"Project",
			self.project,
			["transport_weekend_charge", "transport_public_holiday_charge"],
			as_dict=True,
		) or frappe._dict()

		charges = (
			(
				_("Weekend Duty"),
				settings.weekend_charge_item,
				flt(project.transport_weekend_charge),
				self.total_weekend_days if per_day else self.total_weekend_trips,
			),
			(
				_("Public Holiday Duty"),
				settings.public_holiday_charge_item,
				flt(project.transport_public_holiday_charge),
				self.total_public_holiday_days if per_day else self.total_public_holiday_trips,
			),
		)

		for label, item_code, rate, qty in charges:
			if not (item_code and rate and qty):
				continue

			invoice.append(
				"items",
				{
					"item_code": item_code,
					"qty": qty,
					"rate": rate,
					"description": _("{0} - {1} {2} ({3} to {4})").format(
						label, qty, _("days") if per_day else _("trips"), self.period_from, self.period_to
					),
					"project": self.project,
				},
			)

	def below_round_trip_threshold(self):
		"""Source doc, Transport Timesheet: "If the round trips is below 10 then
		charges will be on trip basis." The monthly rate on the Sales Order
		assumes a normal month of running; a month with fewer round trips than
		the threshold is billed per trip instead. The threshold is in Transport
		Settings (0 switches the rule off)."""
		threshold = frappe.utils.cint(
			frappe.db.get_single_value("Transport Settings", "monthly_round_trip_threshold")
		)
		return bool(threshold) and 0 < frappe.utils.cint(self.total_round_trips) < threshold

	def build_per_trip_lines(self, invoice):
		"""Replace the Sales Order's monthly lines with one per-trip line.

		Needs the contract's rate per round trip (a Project field): the Sales
		Order only knows the monthly price, and dividing it by a thin month's trip
		count would invent a rate nobody agreed. Better to stop and say so than
		to invoice a number that is a guess."""
		settings = frappe.get_single("Transport Settings")
		rate = flt(frappe.db.get_value("Project", self.project, "transport_rate_per_trip"))
		if not rate:
			frappe.throw(
				_("This timesheet has only {0} round trip(s), below the {1} the monthly rate assumes, so it is "
				  "billed per trip - but Project {2} has no Rate per Round Trip. Set it on the Project, "
				  "then create the invoice again.").format(
					self.total_round_trips, settings.monthly_round_trip_threshold, self.project
				),
				title=_("Rate per Round Trip missing"),
			)
		if not settings.transport_service_item:
			frappe.throw(_("Set the Transport Service Item in Transport Settings before billing per trip."))

		invoice.set("items", [])
		invoice.append(
			"items",
			{
				"item_code": settings.transport_service_item,
				"qty": self.total_round_trips,
				"rate": rate,
				"description": _("Transport - {0} round trip(s), {1} to {2}").format(
					self.total_round_trips, format_date_short(self.period_from), format_date_short(self.period_to)
				),
				"project": self.project,
			},
		)
		invoice.remarks = _("Billed per trip: {0} round trips, fewer than the {1} a monthly rate assumes.").format(
			self.total_round_trips, settings.monthly_round_trip_threshold
		)

	def fuel_is_reimbursed_by_client(self):
		"""Source doc, Project Shift Terms: fuel is only rebilled when the
		contract says the company buys it and the client pays it back. "Fuel
		from Client" means the client fuels the vehicle directly and there is
		nothing to invoice. Any shift on the contract carrying the reimbursed
		arrangement is enough - the shifts describe one contract, not one
		vehicle each."""
		project = frappe.get_cached_doc("Project", self.project)
		return any(
			(shift.fuel_arrangement or "") == "Fuel from Company, Reimbursed by Client"
			for shift in (project.get("transport_shifts") or [])
		)

	def build_monthly_vehicle_lines(self, invoice):
		r"""Turn the Vehicle Deployment table into invoice lines.

		The shape comes straight off reference invoice AST-21-02390, which
		reconciles exactly this way:

		    SO line 1 -- deployment 43736  1-31 Aug --> fuel  5,380.54
		              \-------------------------------> rental 6,800
		    SO line 2 -- deployment 30533  1-12 Aug --> fuel  3,154.07
		              |- deployment 51981 13-31 Aug --> fuel  3,629.59
		              \-------------------------------> rental 6,800   <- ONE line
		    SO line 3 -- deployment 51955  1-31 Aug --> fuel  3,558.76
		              \-------------------------------> rental 6,800
		    net 36,122.96  +5% VAT 1,806.15  = 37,929.11

		So: **rental is one line per Sales Order line, fuel is one line per
		deployment row.** A vehicle swapped mid-month does not split the rental
		charge - the customer bought a vehicle-month and got one. Part-month
		proration (design doc 4.4) is deliberately not implemented; neither
		reference invoice prorates, and inventing it would silently undercharge.

		Rates, KM allowance and extra-KM rate are read back off the contract
		line rather than off the deployment row, so a corrected Sales Order can
		never disagree with rows generated earlier."""
		settings = frappe.get_single("Transport Settings")
		deployments = list(self.monthly_deployments)
		if not deployments:
			frappe.throw(_("There are no Vehicle Deployment rows to invoice."))

		terms = frappe.get_all(
			"Sales Order Item",
			filters={"name": ("in", [d.sales_order_item for d in deployments if d.sales_order_item])},
			fields=["name", "transport_extra_km_rate", "uom"],
		)
		terms = {t.name: t for t in terms}

		# make_sales_invoice() maps EVERY unbilled Sales Order line and sets qty
		# to whatever is still unbilled - 12 months on a 12-month PO line. A
		# monthly run bills exactly one month per line, so both the selection and
		# the quantity have to be overridden here.
		#
		# Keeping make_sales_invoice() rather than building items from scratch is
		# deliberate: it is what maintains Sales Order Item.billed_amt, which is
		# how the remaining PO balance stays visible (design doc 4.2 - PO 9586's
		# 24 van-months). The price is that erpnext drops a line from the mapping
		# once billed_amt >= amount, so an exhausted contract line disappears
		# silently. That is caught below and reported instead.
		#
		# CONSEQUENCE FOR OPEN-ENDED CONTRACTS (AST-21-02390 has no PO): the
		# Sales Order line must carry a quantity equal to the contract term in
		# months. A line raised as "qty 1" bills once and then vanishes from
		# every later month. There is no way around this while billed_amt is
		# doing the balance tracking - so an open-ended contract is entered as a
		# fixed term (12 months unless the client says otherwise) and renewed
		# with a fresh Sales Order, which is what the PO-expiry alert is for.
		billable = {}
		for item in list(invoice.items):
			if item.so_detail in terms:
				billable[item.so_detail] = item
			else:
				invoice.remove(item)

		missing = [d.sales_order_item for d in deployments if d.sales_order_item not in billable]
		if missing:
			frappe.throw(
				_(
					"Sales Order {0} has nothing left to bill for {1} of the deployed vehicles - "
					"those contract lines are fully invoiced. Raise a renewal Sales Order before "
					"invoicing this month."
				).format(self.sales_order, len(set(missing)))
			)

		for so_detail, item in billable.items():
			rows = [d for d in deployments if d.sales_order_item == so_detail]
			item.qty = 1
			item.description = self.deployment_description(item, rows)
			item.project = self.project

		if self.fuel_is_reimbursed_by_client():
			for row in deployments:
				if not flt(row.fuel_cost):
					continue
				if not settings.fuel_charge_item:
					frappe.throw(_("Set a Fuel Charge Item in Transport Settings before invoicing fuel."))
				invoice.append(
					"items",
					{
						"item_code": settings.fuel_charge_item,
						"qty": 1,
						# Fuel History stores the pre-VAT figure in `amount` under the
						# label "Total Cost"; `total_cost` is the VAT-inclusive one.
						# Invoice lines are net and the invoice adds 5% output VAT on
						# top, so fuel_cost must be the net figure or VAT is charged
						# twice.
						"rate": flt(row.fuel_cost),
						"description": _("Fuel Cost - Actual - Vehicle {0} ({1} to {2})").format(
							row.vehicle, format_date_short(row.from_date), format_date_short(row.to_date)
						),
						"project": self.project,
					},
				)

		for row in deployments:
			extra = flt(row.extra_km_run)
			if extra <= 0:
				continue
			rate = flt(terms.get(row.sales_order_item, frappe._dict()).transport_extra_km_rate)
			if not rate:
				# An excess with no agreed rate is a contract question, not a
				# number to guess. Billing it at zero would hide the overrun.
				frappe.throw(
					_("Row #{0}: {1} extra km with no Extra KM Rate on the Sales Order line.").format(
						row.idx, extra
					)
				)
			if not settings.extra_km_charge_item:
				frappe.throw(_("Set an Extra KM Charge Item in Transport Settings before invoicing excess kilometres."))
			invoice.append(
				"items",
				{
					"item_code": settings.extra_km_charge_item,
					"qty": extra,
					"rate": rate,
					"description": _("Extra KM Charge - Vehicle {0} - {1} km over allowance").format(
						row.vehicle, extra
					),
					"project": self.project,
				},
			)

	def deployment_description(self, item, rows):
		"""Replaces the hand-typed vehicle/date text on the reference invoice
		("Vehicle #46905(Old Plate#63015)51981 / 1-12 August 2026 Vechicle
		:30533 ..."). One line per vehicle, and dates only where the month was
		shared, so an unswapped vehicle stays a single clean line."""
		parts = [item.item_name or item.item_code, _("1 Month")]
		for row in rows:
			if len(rows) == 1:
				parts.append(_("Vehicle {0}").format(row.vehicle))
			else:
				parts.append(
					_("Vehicle {0} ({1} to {2})").format(
						row.vehicle, format_date_short(row.from_date), format_date_short(row.to_date)
					)
				)
		return "<br>".join(parts)

	@frappe.whitelist()
	def create_sales_invoice(self):
		if not any(role in frappe.get_roles() for role in ACCOUNTS_ROLES):
			frappe.throw(_("Not permitted to create the Invoice."), frappe.PermissionError)
		if self.status != "Customer Approved":
			frappe.throw(_("Timesheet must be Customer Approved before invoicing."))
		if self.sales_invoice:
			frappe.throw(_("Sales Invoice {0} has already been created from this Timesheet.").format(self.sales_invoice))
		if not self.sales_order:
			frappe.throw(_("No submitted Sales Order found for Project {0}.").format(self.project))

		from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice

		invoice = make_sales_invoice(self.sales_order)
		invoice.transport_timesheet = self.name
		invoice.grn_status = "Pending"
		invoice.invoice_submission_status = "Not Submitted"

		# A transport contract is one long-lived Sales Order invoiced every
		# month, and make_sales_invoice() copies the order's payment schedule
		# as-is. That schedule's due date is fixed at the order's own date, so
		# from the second month onward ERPNext rejects the invoice with "Due
		# Date cannot be before Posting Date" - the contract would invoice once
		# and then break. Clearing both lets accounts_controller rebuild the
		# schedule from this invoice's posting date and the customer's payment
		# terms, which is what a monthly billing run actually needs.
		invoice.payment_schedule = []
		invoice.due_date = None

		# Weekend / public-holiday charges price extra DUTY, which only means
		# something when the contract is billed per trip or per day. A monthly
		# vehicle rate already covers the whole month including weekends.
		if self.billing_basis == "Monthly per Vehicle":
			self.build_monthly_vehicle_lines(invoice)
		else:
			if self.below_round_trip_threshold():
				self.build_per_trip_lines(invoice)
			self.add_weekend_holiday_charges(invoice)

		invoice.insert()

		self.db_set({"sales_invoice": invoice.name, "status": "Invoiced"})

		certificate = frappe.get_doc({
			"doctype": "Certificate of Completion",
			"transport_timesheet": self.name,
		}).insert()
		self.db_set("certificate_of_completion", certificate.name)
		frappe.db.set_value("Sales Invoice", invoice.name, "certificate_of_completion", certificate.name)

		return invoice.name


def ensure_draft_timesheet(trip):
	"""Make sure an approved Trip is on a Draft Timesheet, creating one if needed.

	Reuses the Draft Timesheet for the project whose period covers the trip's
	date; otherwise opens one for the calendar month. Pulling the trips in is
	idempotent (see populate_trips), so every approval in a month just refreshes
	the same Draft. If the month's earlier timesheet has already gone for
	approval it is left alone - it is the billing record - and the late trip
	lands on a new Draft instead.

	A monthly-per-vehicle contract bills the vehicle-month, not trips, so it has
	nothing to pull. Returns {"name", "created"} or None when switched off or not
	applicable."""
	from frappe.utils import get_first_day, get_last_day

	if not frappe.db.get_single_value("Transport Settings", "auto_create_timesheet_on_approval"):
		return None
	if not trip.project:
		return None
	if frappe.db.get_value("Project", trip.project, "transport_billing_basis") == "Monthly per Vehicle":
		return None

	trip_date = getdate(trip.trip_date)
	existing = frappe.get_all(
		"Transport Timesheet",
		filters={
			"project": trip.project,
			"status": "Draft",
			"period_from": ("<=", trip_date),
			"period_to": (">=", trip_date),
		},
		pluck="name",
		order_by="creation desc",
		limit=1,
	)

	created = not existing
	if existing:
		timesheet = frappe.get_doc("Transport Timesheet", existing[0])
	else:
		timesheet = frappe.get_doc(
			{
				"doctype": "Transport Timesheet",
				"project": trip.project,
				"period_from": get_first_day(trip_date),
				"period_to": get_last_day(trip_date),
			}
		)
		timesheet.flags.ignore_permissions = True
		timesheet.insert()

	timesheet._populate_trips(ignore_permissions=True)
	return {"name": timesheet.name, "created": created}
