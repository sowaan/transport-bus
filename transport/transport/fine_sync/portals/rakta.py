# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

"""Ras Al Khaimah Transport Authority (RAKTA), smart.rakta.gov.ae.

**No sign-in, no CAPTCHA, and no OTP.** Measured on 2026-09-18 against the live
site: the Fines Enquiry tab on `/home/login` is a public form. The page is
*named* login and carries a "Sign in" button for the account features, which is
how this portal came to be recorded as login-gated - `registry.py` and
`srta.py` both said so, and both were wrong. Nothing on the fines route asks
who you are.

**This portal is queried one plate at a time, and that is the whole shape of
it.** TAMM carries the fleet in a query parameter and RTA takes a traffic file
number, so on both a single search returns every vehicle's fines. RAKTA has no
such route. The request body is built in `fineSubmitForm()` as

    {PlateEmirate, PlateCode, PlateNumber}

and there is no company or fleet variant: `CompanyEnquiry` returns company
details and `VehicleEnquiry` returns vehicles, neither returns fines. So the
reader loops the fleet, and a run's cost is linear in the number of vehicles.
That is why `coverage` here names *plates* rather than lists.

**Why the server cannot do this itself.** The request is not plain JSON. The
Angular app posts `{"payload": "<base64>"}` - the parameters are encrypted
client-side by `postEnquiryAPICallWithToken` before they leave the browser. A
server-side HTTP client would have to reimplement that encryption and would
break the first time the key rotated. Driving the real form in a real browser
means the page does its own encrypting, which is the durable arrangement
whatever else changes. `fetch_implemented` stays False; this portal is read by
the extension or not at all.

**The DOM contract below was read out of the compiled Angular template**
(chunk 27 of the production bundle), not guessed from a screenshot, and not
obtained by searching for a stranger's plate. The row template binds exactly
six cells:

    td  FineID          td  FineDetails     td  FineAmount
    td  FineIssueDate   td > div FineStatus td.text-center  actions

The fifth value is wrapped in a `<div>` and the others are bare text, so the
extractor reads `textContent` positionally rather than trusting the shape.

`FineStatus` is a closed set, and this too is from the template rather than
from observation - the action cell switches on the literal strings:

    "Not Paid"   "Paid"   "Waived"   "Cancel"

**What is NOT verified**, and must not be written as though it were:

* The rendered format of `FineAmount` and `FineIssueDate`. The template proves
  `FineAmount` is numeric in the model (`e.FineAmount > 0` gates the Pay
  button) but says nothing about how it is printed, and nothing at all about
  the date format. Both are parsed defensively below; neither has been seen
  with real data.
* Whether a status outside those four literals can occur.
* **Scope.** This is the Transport Authority, not the police. `srta.py` already
  establishes that a clean result from a transport authority says nothing about
  a vehicle's police fines, and whether RAKTA's `FineDetails` covers traffic
  offences or only transport and permit violations has not been established.
  Recorded as unknown; do not present a clean RAKTA result as "no fines".

The action cell holds a `button.play_btn` labelled Pay, wired to
`navigateToPaymentPage`. The reader never touches it, for the same reason it
never touches TAMM's or MOI's.
"""

import re

import frappe

from transport.transport.fine_sync.base import FetchedFine, FineFetcher, FineFetchError
from transport.transport.vehicle_plate import PLATE_FIELDS, normalize_emirate

SEARCH_URL = "https://smart.rakta.gov.ae/home/login"

# Our `plate_emirate` Select options mapped onto the values RAKTA's own emirate
# `<select>` carries. Read off the live options list on 2026-09-18, which also
# offered "OMAN" and "Saudi Arabia" - foreign registrations we do not hold and
# deliberately do not map.
#
# Every one of the seven emirates is queryable here, which is what makes this
# portal worth the per-plate cost: it is not limited to RAK-registered
# vehicles, so an Abu Dhabi fleet can be swept against it.
PORTAL_EMIRATE = {
	"Abu Dhabi": "AUH",
	"Dubai": "DXB",
	"Sharjah": "SHJ",
	"Ajman": "AJM",
	"Umm Al Quwain": "UAQ",
	"Ras Al Khaimah": "RAK",
	"Fujairah": "FUJ",
}

# And back again. The reader stamps rows with the code it submitted - "AUH",
# because that is what the portal's own `<select>` takes - and `plate_emirate`
# has to be turned back into a `EMIRATES` option before it reaches
# `_vehicle_for_plate`. `normalize_emirate` does not know these codes, so an
# unconverted "AUH" would normalise to None, the emirate would drop out of the
# filter, and an Abu Dhabi fine would be free to match a Sharjah vehicle
# sharing its code and number. That is the exact fault that was fixed for
# Dubai; it is not being reintroduced through a different door.
EMIRATE_FROM_PORTAL = {code: emirate for emirate, code in PORTAL_EMIRATE.items()}

# RAKTA's four status literals mapped onto the Portal Status Select, whose only
# accepted values are "", "Payable" and "Unpayable". Anything unrecognised
# becomes "" rather than a guess: an invalid Select value fails the insert and
# takes the rest of the run down with it, which is exactly how the RTA
# "Non-Payable" bug stranded a Failed run holding real staged rows.
PORTAL_STATUS_BY_FINE_STATUS = {
	"Not Paid": "Payable",
	# Settled. Kept rather than dropped so a fine that was paid outside the
	# system still reconciles against whatever was invoiced for it.
	"Paid": "Unpayable",
	# Forgiven. Not payable, and not a debt.
	"Waived": "Unpayable",
	"Cancel": "Unpayable",
}

AMOUNT_RE = re.compile(r"-?\d[\d,]*\.?\d*")

# The results table, read positionally.
#
# Positional and not header-driven, which is the opposite of the choice made in
# `tamm.py`, and the reason is in the markup: these `<th>` cells are rendered
# through the `translate` pipe, so their text is whatever language the visitor
# last selected. Reading by header would work in English and silently return
# nothing in Arabic. The column ORDER is fixed in the compiled template and
# does not vary by language.
#
# `_status` comes from the cell whose value the template wraps in a `<div>`;
# `textContent` flattens that, so the same index works either way.
EXTRACT_ROWS_JS = """() => {
  const list = document.querySelector('#fines_enquiry .fine_enquiry_list');
  if (!list) return null;

  const table = list.querySelector('table.mytable');
  if (!table) {
    // The portal renders <h4 class="list_heading">No Record Found</h4> in
    // place of the table. That is an answer - zero fines for this plate - and
    // is reported as an empty array, never as a failure to read.
    return list.querySelector('h4') ? [] : null;
  }

  return [...table.querySelectorAll('tbody tr')].map(tr => {
    const cells = [...tr.children].map(td => (td.textContent || '').trim());
    return {
      _fineId:     cells[0] || '',
      _details:    cells[1] || '',
      _amount:     cells[2] || '',
      _issuedDate: cells[3] || '',
      _status:     cells[4] || '',
    };
  }).filter(row => row._fineId);
}"""


class RaktaFetcher(FineFetcher):
	"""RAKTA: public per-plate fines enquiry, read in the operator's browser."""

	# Nothing here is a sign-in wall, so nobody has to be present to answer
	# anything. It is still not schedulable - see `supports_unattended`.
	client_unattended = True

	# False, and for a different reason than everywhere else. This is not about
	# a challenge nobody has measured; it is that the server has no supported
	# way to make the request at all (the encrypted payload, above). Turning
	# this on would need the encryption reimplemented, not a selector fix.
	fetch_implemented = False

	# The scheduler stays off this portal. A sweep costs one page load and one
	# search per vehicle, so an unattended nightly run would put the fleet's
	# whole plate list through a government portal on a timer, from one
	# address, with nobody watching the result. That is a decision for the
	# client to take explicitly, not a default.
	supports_unattended = False

	# No UAE Pass, so no code to put on anyone's screen.
	supports_relay = False

	client_reader = "rakta"
	client_origin = "https://smart.rakta.gov.ae"

	# This portal ships an extractor and nothing else. There is no pager - the
	# template renders one `*ngFor` over the whole `fineData` array with no
	# paginator - and no detail view, so `NEXT_PAGE_JS` and `READ_PANEL_JS`
	# would be stubs standing in for machinery that does not exist. Declaring
	# what is actually shipped keeps the generator's drift check meaningful for
	# the portals that do have all three.
	client_extractors = ("EXTRACT_ROWS_JS",)

	def fetch_for_vehicle(self, plate_parts):
		raise FineFetchError(f"{self.portal.name}: {self._server_reason()}")

	def fetch_for_traffic_file(self, traffic_file_number, **kwargs):
		raise FineFetchError(
			f"{self.portal.name} has no traffic-file route. It is queried one plate at a "
			"time - see the module docstring."
		)

	@staticmethod
	def _server_reason():
		return (
			"this portal encrypts its search parameters in the browser, so the server "
			"cannot reproduce the request. It is read through the extension instead."
		)

	def client_fetch_target(self, traffic_file_number=None):
		"""The enquiry page, plus the plates the reader has to work through.

		**The traffic file number is ignored here, and the signature keeps it
		only because the caller passes it positionally.** RAKTA does not have a
		fleet identifier of any kind.

		What goes over instead is the fleet's plates, and that is a larger
		disclosure to the browser than any other portal makes - TAMM hands over
		a URL and RTA a single number. It is unavoidable: there is no query
		that returns more than one vehicle's fines, so the plates are the only
		possible input. Two things bound it. The plates are already visible on
		the vehicles themselves, and `ingest_client_fetch` still refuses to
		accept a fleet identifier back, so a browser cannot attach rows to a
		fleet of its choosing.

		Vehicles missing any plate part, or carrying an emirate RAKTA's form
		does not offer, are left out of the list and named in `unqueryable` so
		the run can record them as never-asked rather than as clean.
		"""
		queryable, unqueryable = [], []
		vehicles = frappe.get_all(
			"Rental Vehicle",
			fields=["name", "license_plate", *PLATE_FIELDS],
			order_by="license_plate",
		)

		for vehicle in vehicles:
			emirate = normalize_emirate(vehicle.get("plate_emirate"))
			code = (vehicle.get("plate_code") or "").strip()
			number = (vehicle.get("plate_number") or "").strip()
			portal_emirate = PORTAL_EMIRATE.get(emirate) if emirate else None

			if not (portal_emirate and code and number):
				unqueryable.append(
					{
						"plate": vehicle.get("license_plate") or vehicle.get("name"),
						"reason": "no plate emirate RAKTA offers"
						if (code and number)
						else "incomplete plate",
					}
				)
				continue

			queryable.append({"emirate": portal_emirate, "code": code, "number": number})

		if not queryable:
			raise FineFetchError(
				f"{self.portal.name} is queried one plate at a time, and no vehicle in the "
				"fleet has a complete plate in an emirate this portal offers."
			)

		return {
			"url": SEARCH_URL,
			"origin": self.client_origin,
			# The enquiry tabs are client-side state on this one path; no search
			# navigates away from it, so the whole portal is under this prefix.
			"path_prefix": "/home",
			"reader": self.client_reader,
			"unattended": self.client_unattended,
			# **Only the plates.** The vehicles with incomplete plate data are
			# deliberately NOT sent, and this is not an oversight.
			#
			# The reader reports unreachable plates in `coverage`, and
			# background.js turns any `coverage` entry with `read === null`
			# into `truncated`, which `ingest_client_fetch` turns into
			# "Completed with Errors: the browser stopped before the end of
			# the list". A fleet with even one unplated vehicle would therefore
			# mark EVERY run degraded, with a reason that is false - the
			# browser did not stop early, those vehicles were never a question
			# it was asked. Worse, it would bury a real budget truncation in a
			# permanent baseline of noise.
			#
			# `truncated` has to keep meaning "something the reader tried to
			# read is missing". A vehicle with no plate is a data-quality
			# problem on the vehicle record, and belongs where the fleet is
			# edited rather than in a fetch's status.
			"prefill": {"plates": queryable},
		}

	def _to_fine(self, row):
		"""One results-table row as a FetchedFine.

		A row with no `FineID` is dropped rather than staged under a synthetic
		key: the fine number is what dedup runs on and what an operator types
		into the portal to find the thing again.
		"""
		ticket = (row.get("_fineId") or "").strip()
		if not ticket:
			return None

		status = (row.get("_status") or "").strip()
		# None when the browser sent a code this build does not know. Left as
		# None rather than passed through: an unrecognised emirate must widen
		# the match to "any emirate", which `_vehicle_for_plate` already
		# handles, not narrow it to a value no vehicle can ever hold.
		emirate = EMIRATE_FROM_PORTAL.get((row.get("_plateEmirate") or "").strip().upper())
		code = (row.get("_plateCode") or "").strip()
		number = (row.get("_plateNumber") or "").strip()

		return FetchedFine(
			ticket_number=ticket,
			amount=self._amount(row.get("_amount")),
			fine_datetime=self._datetime(row.get("_issuedDate")),
			fine_type=(row.get("_details") or "").strip() or None,
			# The table has no location column at all. Left absent rather than
			# filled with the issuing authority, which is not a location.
			fine_location=None,
			# Stamped by the reader from the search it had just submitted, not
			# read from the row - this table has no plate column, because the
			# plate is the query. Without this every RAKTA fine would arrive
			# unmatchable and stage as unlinked.
			plate=" ".join(part for part in (emirate, code, number) if part),
			# No black-points column on this portal. Zero here means "not
			# reported", and the absence is recorded in `raw` so it is not
			# mistaken for a measured zero.
			black_points=0,
			raw={
				"issuing_authority": "RAK Transport Authority",
				"face_amount": self._amount(row.get("_amount")),
				# RAKTA prints one figure. Recorded as absent rather than equal
				# to the face amount, which would read as a discount that was
				# offered and declined.
				"discounted_amount": None,
				"plate_emirate": emirate,
				"plate_code": code,
				"plate_number": number,
				"description": (row.get("_details") or "").strip() or None,
				# The date exactly as the portal printed it. Kept because
				# `_datetime` reads numeric forms day-first on an assumption
				# that has not been checked against a real row - if that turns
				# out to be wrong, this is what the correction is made from.
				"issued_date_text": (row.get("_issuedDate") or "").strip() or None,
				"portal_status": PORTAL_STATUS_BY_FINE_STATUS.get(status, ""),
				# The portal's own word, kept because the mapping above is
				# lossy - Paid, Waived and Cancel all land on "Unpayable", and
				# this is the only place that difference survives.
				"rakta_status": status or None,
				"black_points_reported": False,
				"row": row,
			},
		)

	@classmethod
	def _amount(cls, text):
		"""The fine amount, or 0.0.

		Deliberately tolerant: the rendered format has not been measured, so
		this strips a currency word and takes the first number it finds rather
		than asserting a layout.
		"""
		found = AMOUNT_RE.findall((text or "").replace("AED", " "))
		return float(found[0].replace(",", "")) if found else 0.0

	@staticmethod
	def _datetime(text):
		"""The issue date as a Frappe datetime string, or None.

		It cannot be passed through as text: `fine_datetime` on Traffic Fine
		Staging is a Datetime field, and handing it an unrecognised string gets
		it coerced rather than rejected.

		**The format is unmeasured** - the template interpolates `FineIssueDate`
		with no date pipe, so whatever the API sends is what is printed, and no
		row has been seen with real data. The candidates below are attempted in
		order and anything else returns None, which stages the fine without a
		date for someone to correct. A fine dated today because a parse fell
		through is a liability carrying a false date; that is the worse outcome
		and this will not produce it.

		Numeric forms are read **day-first**, the UAE convention. That is an
		assumption, and it is the one thing here worth confirming against a real
		row before anyone trusts these dates: for days 1-12 a month-first portal
		would parse cleanly and wrongly. `raw["issued_date_text"]` keeps the
		original either way, so a wrong reading stays recoverable.
		"""
		from datetime import datetime

		value = (text or "").strip()
		if not value:
			return None
		for fmt in (
			"%Y-%m-%dT%H:%M:%S",
			"%Y-%m-%d %H:%M:%S",
			"%Y-%m-%d",
			"%d/%m/%Y %H:%M:%S",
			"%d/%m/%Y %H:%M",
			"%d/%m/%Y",
			"%d-%m-%Y %H:%M",
			"%d-%m-%Y",
			"%d %b %Y, %I:%M %p",
			"%d %b %Y %H:%M",
			"%d %b %Y",
		):
			try:
				return datetime.strptime(value.split(".")[0], fmt).strftime("%Y-%m-%d %H:%M:%S")
			except ValueError:
				continue
		return None
