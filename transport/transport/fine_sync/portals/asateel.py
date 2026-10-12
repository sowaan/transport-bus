# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

"""Asateel: the permit registry for the fleet, read in the operator's browser.

**This is a permit registry, not a fines or a toll portal.** Nothing it lists is
chargeable, so - like `salik.py` - this class is not a `FineFetcher`, has no
`_to_fine`, is not in the fines registry, and `ingest_client_fetch` cannot be
handed its rows. They go to `ingest_client_permits`, which records a permit's
expiry date on the vehicle and lets the existing Compliance Document sync carry
it from there.

What the page is, read from the saved copy the client sent (2026-10-10):

* `asateelplus.itc.gov.ae/tpc-portal/manage-vehicle`, "Manage Vehicles". A
  Vue/Vuetify single-page app: its own sign-in at the same host, a "Log Out"
  link only once signed in.
* One row per vehicle: plate (emirate, plate category, number), traffic code,
  vehicle type, business domain, **Permit Validity**, vehicle status. Ten a
  page, with a Bootstrap pager (`ul.pagination`) beneath; the page's own tiles
  say how many vehicles and permits there are in all (Total Vehicles, Registered
  Vehicles, Total Permits, Active Permits), which is what the reader checks its
  count against.
* Permit Validity is either the words "No Active Permit", or a number of days
  and the expiry date ("55 Days" over "Dec 31, 2026"). Nothing else has been
  seen. The capture holds 19 active permits' worth of tiles but only one active
  row, so how an EXPIRED permit is shown is not known: such a cell is passed on
  as it is, reported, and never turned into a date.
* The list carries no permit NUMBER. That is on the vehicle's own page
  ("Permits" tab), which was captured on a vehicle with no permit and so shows
  nothing to read. It is not read here.

What is not known and so is not assumed: the empty list, the expired-permit
wording above, the page's loading indicator (the reader waits for the rows to
stop changing rather than for a spinner), and whether the page keeps a filter
from one visit to the next (the reader refuses a count that disagrees with the
page's own total instead of trusting the filter is clear).
"""

import re

# The six header labels after the select-all checkbox, in order. Checked by the
# reader before it trusts a row: a re-themed page, or the Arabic one, would
# otherwise be read by position into the wrong fields.
EXPECTED_HEADERS = (
	"Vehicle Details",
	"Traffic Code",
	"Vehicle Type Name",
	"Business Domain",
	"Permit Validity",
	"Vehicle Status",
)


EXTRACT_ROWS_JS = r"""() => {
	// The vehicles table, not any other table the app may add to the page.
	const table = document.querySelector('.v-data-table table');
	if (!table) return null;

	const text = (el) => (el ? el.textContent : '').replace(/\s+/g, ' ').trim();

	const HEADERS = ['Vehicle Details', 'Traffic Code', 'Vehicle Type Name', 'Business Domain', 'Permit Validity', 'Vehicle Status'];

	// Cell 0 is the select checkbox. The label is in .header-text; the th's own
	// text also carries a sort icon's ligature name.
	const head = [...table.querySelectorAll('thead th')].slice(1, 1 + HEADERS.length)
		.map((th) => text(th.querySelector('.header-text') || th));
	const headOk = head.length === HEADERS.length && HEADERS.every((h, i) => head[i] === h);

	const rows = [];
	for (const tr of table.querySelectorAll('tbody tr')) {
		// An expandable table may interleave detail rows, and an empty one shows a
		// single full-width message. Neither is a vehicle.
		if ((tr.className || '').includes('expanded')) continue;
		const cells = [...tr.children];
		if (cells.length === 1 && cells[0].hasAttribute('colspan')) continue;

		const plate = cells[1] || null;
		const state = plate ? plate.querySelector('.plate-number--state') : null;
		const number = plate ? plate.querySelector('.plate-number--number') : null;
		// The emirate is the other cell of the plate's top line, beside the category.
		const top = state ? state.parentElement : null;
		const emirate = top ? [...top.children].find((c) => c !== state) : null;

		const row = {
			_emirate: text(emirate),
			_code: text(state),
			_number: text(number),
			_traffic_code: text(cells[2]),
			_type: text(cells[3]),
			_domain: text(cells[4]),
			_permit: text(cells[5]),
			_status: text(cells[6]),
		};
		// False when the row cannot be trusted by position: too few cells, or no
		// plate or traffic code to say which vehicle it is.
		row._ok = headOk && cells.length >= 8 && !!(row._emirate && row._code && row._number) &&
			/^\d+$/.test(row._traffic_code);
		rows.push(row);
	}
	return rows;
}"""


# Clicks the pager's "next" arrow and says whether there was one to click. The
# first/previous controls are drawn as inert spans when there is nowhere to go,
# and the next arrow stops being a button on the last page - so "no button" and
# "disabled" both mean the end.
NEXT_PAGE_JS = r"""() => {
	const pager = document.querySelector('ul.pagination');
	if (!pager) return false;
	const next = pager.querySelector('button[aria-label="Go to next page"]');
	if (!next || next.disabled || next.getAttribute('aria-disabled') === 'true') return false;
	next.click();
	return true;
}"""


MONTHS = {
	"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
	"jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# "55 Days Dec 31, 2026" - the days and the date are two lines of one cell.
ACTIVE_RE = re.compile(r"^(\d+) Days? ([A-Za-z]{3,9}) (\d{1,2}), (\d{4})$")
NO_PERMIT = "no active permit"


class AsateelPermitReader:
	"""Reads the vehicle permits the signed-in Asateel account lists.

	Deliberately not a `FineFetcher`; see the module docstring. The class exists
	so the extension's generator can find `client_reader`, `client_origin` and the
	extractor constants the same way it does for every other portal.
	"""

	client_reader = "asateel"
	client_origin = "https://asateelplus.itc.gov.ae"
	client_extractors = ("EXTRACT_ROWS_JS", "NEXT_PAGE_JS")

	# Foreground: the operator signs in themselves, in this tab.
	client_unattended = False

	@staticmethod
	def client_fetch_target():
		"""The vehicles page. Nothing identifying is sent: the account decides what shows."""
		return {
			"url": "https://asateelplus.itc.gov.ae/tpc-portal/manage-vehicle",
			"origin": AsateelPermitReader.client_origin,
			"path_prefix": "/tpc-portal/manage-vehicle",
			"reader": AsateelPermitReader.client_reader,
			"unattended": AsateelPermitReader.client_unattended,
		}

	@classmethod
	def to_permit(cls, row):
		"""One vehicle row as a dict, with the permit classed as none / active / other.

		Raises ValueError for a row that cannot say which vehicle it is. The
		permit text is different: a wording nobody has seen (an expired permit is
		the likely one) is classed "other" and carried through verbatim, so the
		rest of the list is still usable and the odd one is reported by name
		rather than failing the read or being guessed at.
		"""
		emirate = (row.get("_emirate") or "").strip()
		code = (row.get("_code") or "").strip()
		number = (row.get("_number") or "").strip()
		traffic_code = (row.get("_traffic_code") or "").strip()
		if not (emirate and code and number) or not traffic_code.isdigit():
			raise ValueError("a vehicle with no plate or traffic code")

		permit_text = " ".join((row.get("_permit") or "").split())
		permit, expiry = "other", None
		if permit_text.lower() == NO_PERMIT:
			permit = "none"
		else:
			found = ACTIVE_RE.match(permit_text)
			month = MONTHS.get(found.group(2)[:3].lower()) if found else None
			if found and month:
				permit = "active"
				expiry = f"{int(found.group(4)):04d}-{month:02d}-{int(found.group(3)):02d}"

		return {
			"emirate": emirate,
			"plate_code": code,
			"plate_number": number,
			"traffic_code": traffic_code,
			"business_domain": " ".join((row.get("_domain") or "").split()) or None,
			"vehicle_status": " ".join((row.get("_status") or "").split()) or None,
			"permit": permit,
			"expiry_date": expiry,
			"permit_text": permit_text,
		}
