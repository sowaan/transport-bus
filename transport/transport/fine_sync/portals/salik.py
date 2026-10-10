# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

"""Salik: the toll charges the customer portal lists, read in the operator's browser.

**These are charges, not fines.** That decides the shape of this module.

Everything else in `portals/` turns a row into a `FetchedFine`, and a fine is
staged in Traffic Fine Staging, which invoices on save. A Salik crossing run
through that route would be invoiced as though it were a penalty - including
the crossings Salik charged AED 0.00 for. So this class has no `_to_fine`, is
not in `registry.py`, and `ingest_client_fetch` (which refuses a fetcher with
no `_to_fine`) cannot accept its rows even by mistake. Its rows go to a
`Toll Crossing` record through their own ingest instead.

Salik *fines* are a different page on the same site (`/en/account/violations`).
Nobody has captured it, so nothing here reads it.

What the page is, read from the saved copy the client sent (2026-10-10):

* `customers.salik.ae/en/account/trips`, the "Transactions" page. The public
  `www.salik.ae` pages are a different site; only the customer portal is read.
* The toll table is `#trips-container table.toll-trips-table`. Each crossing is
  TWO rows: a `tr.open` carrying date, time, plate, gate, direction and the
  total in AED including VAT, and the `tr.trips-table-drop` after it carrying
  tag number, transaction id, post date and the "Toll Schedule" label. The drop
  row is in the DOM whether or not it is expanded, so nothing is clicked to
  read it. An expanded crossing has the class `open active`, not `open` - a
  match on the exact class misses it, which is how an early count of this page
  came up one short.
* Ten crossings per load, then a `#loadMore` button. The page also holds
  parking trips with their own `#ParkingloadMore`; this reader never touches
  that tab.
* A crossing can be charged 0.00. That is a real value, not a missing one.
* Labels and dates are English ("09 Oct 2026", "Transaction ID"). The reader
  refuses a page whose language is not English rather than guessing at Arabic.

What the page does NOT tell us, and so is still unverified: what it shows when
there are no crossings in the window, whether the 7- and 30-day filters reload
the table without navigating (so they are not used - the reader reads the
window the page opens on, 24 hours, and says so), and where sign-in returns the
operator to.
"""

import re

# Column order of the header row, checked by the reader before it trusts a row.
# A page that re-themed and moved a column would otherwise be read by position
# into the wrong fields and look entirely plausible.
EXPECTED_HEADERS = (
	"Trip date",
	"Trip time",
	"Plate",
	"Toll gate",
	"Direction",
	"Total amount (AED)",
)

# The four labels under each crossing's drop row, in order.
EXPECTED_LABELS = ("Tag number", "Transaction ID", "Transaction post date", "Toll Schedule")


EXTRACT_ROWS_JS = r"""() => {
	// Scoped to the trips container. The page holds a second table for parking
	// trips and a statements table; neither is a toll crossing.
	const table = document.querySelector('#trips-container table.toll-trips-table');
	if (!table) return null;

	const text = (el) => (el ? el.textContent : '').replace(/\s+/g, ' ').trim();

	const HEADERS = ['Trip date', 'Trip time', 'Plate', 'Toll gate', 'Direction', 'Total amount (AED)'];
	const LABELS = ['Tag number', 'Transaction ID', 'Transaction post date', 'Toll Schedule'];

	const head = [...table.querySelectorAll('thead td, thead th')].slice(0, HEADERS.length).map(text);
	const headOk = HEADERS.every((h, i) => (head[i] || '').startsWith(h));

	const rows = [];
	for (const tr of table.querySelectorAll('tr')) {
		// classList, not a string compare: an expanded crossing is "open active".
		if (!tr.classList.contains('open') || tr.classList.contains('trips-table-drop')) continue;

		const cells = [...tr.children];
		// The drop row is the very next row. Pairing by position in the table would
		// shift every later crossing by one if a single drop row were missing.
		const next = tr.nextElementSibling;
		const drop = next && next.classList.contains('trips-table-drop') ? next : null;
		const desc = drop ? [...drop.querySelectorAll('.description')] : [];

		// Each description is a value, a <br>, then its label.
		const value = (d) => (d && d.firstElementChild ? text(d.firstElementChild) : '');
		const label = (d) => (d && d.lastElementChild ? text(d.lastElementChild) : '');

		const labelsOk = desc.length === LABELS.length && LABELS.every((l, i) => label(desc[i]) === l);

		rows.push({
			_date: text(cells[0]),
			_time: text(cells[1]),
			_plate: text(cells[2]),
			_gate: text(cells[3]),
			_direction: text(cells[4]),
			_amount: text(cells[5]),
			_tag: value(desc[0]),
			_txn: value(desc[1]),
			_post: value(desc[2]),
			_schedule: value(desc[3]),
			// False when the row cannot be trusted by position: too few cells, no
			// drop row, or labels that are not the four expected, in order.
			_ok: headOk && cells.length >= 6 && labelsOk,
		});
	}
	return rows;
}"""


MONTHS = {
	"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
	"jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
DATE_RE = re.compile(r"^(\d{1,2}) ([A-Za-z]{3}) (\d{4})$")
TIME_RE = re.compile(r"^(\d{1,2}):(\d{2}):(\d{2}) ?([AaPp][Mm])$")
AMOUNT_RE = re.compile(r"^\d+(?:,\d{3})*(?:\.\d+)?$")


class SalikTripsReader:
	"""Reads the toll crossings the signed-in Salik account lists.

	Deliberately not a `FineFetcher`: it fetches nothing on the server, stages no
	fines, and must not be routed by `registry.py`. The class exists so the
	extension's generator can find `client_reader`, `client_origin` and
	`EXTRACT_ROWS_JS` the same way it does for every other portal.
	"""

	client_reader = "salik"
	client_origin = "https://customers.salik.ae"
	client_extractors = ("EXTRACT_ROWS_JS",)

	# Foreground: the operator signs in themselves, in this tab.
	client_unattended = False

	AUTHORITY = "Salik"

	@staticmethod
	def client_fetch_target():
		"""The trips page. Nothing identifying is sent: the account decides what shows."""
		return {
			"url": "https://customers.salik.ae/en/account/trips",
			"origin": SalikTripsReader.client_origin,
			"path_prefix": "/en/account/trips",
			"reader": SalikTripsReader.client_reader,
			"unattended": SalikTripsReader.client_unattended,
		}

	@classmethod
	def to_crossing(cls, row):
		"""One crossing as the fields of a `Toll Crossing`, or None for a row that is not one.

		None only for a row with no transaction id: that id is what makes a re-read
		idempotent, and a crossing without it cannot be stored under a stable name.
		Anything else that does not parse RAISES. A crossing with an unreadable
		amount or time must not become a quiet 0.00 at midnight.
		"""
		txn = (row.get("_txn") or "").strip()
		if not txn:
			return None
		if not txn.isdigit():
			raise ValueError(f"Transaction id is not a number: {txn!r}")

		amount = cls._amount(row.get("_amount"))
		crossed_on = cls._crossed_on(row.get("_date"), row.get("_time"))
		posted = (row.get("_post") or "").strip()

		return {
			"authority": cls.AUTHORITY,
			"transaction_id": txn,
			"crossed_on": crossed_on,
			"posted_on": cls._date(posted) if posted else None,
			"plate_text": " ".join((row.get("_plate") or "").split()) or None,
			"tag_number": (row.get("_tag") or "").strip() or None,
			"gate": (row.get("_gate") or "").strip() or None,
			"direction": (row.get("_direction") or "").strip() or None,
			"toll_schedule": " ".join((row.get("_schedule") or "").split()) or None,
			"amount": amount,
		}

	@staticmethod
	def _date(text):
		"""'09 Oct 2026' as 'YYYY-MM-DD'. Parsed by hand: strptime's %b follows the locale."""
		found = DATE_RE.match((text or "").strip())
		month = MONTHS.get(found.group(2).lower()) if found else None
		if not found or not month:
			raise ValueError(f"Unreadable date: {text!r}")
		return f"{int(found.group(3)):04d}-{month:02d}-{int(found.group(1)):02d}"

	@classmethod
	def _crossed_on(cls, date_text, time_text):
		found = TIME_RE.match((time_text or "").strip())
		if not found:
			raise ValueError(f"Unreadable time: {time_text!r}")
		hour, minute, second = int(found.group(1)), int(found.group(2)), int(found.group(3))
		if not (1 <= hour <= 12 and minute < 60 and second < 60):
			raise ValueError(f"Unreadable time: {time_text!r}")
		hour = hour % 12 + (12 if found.group(4).lower() == "pm" else 0)
		return f"{cls._date(date_text)} {hour:02d}:{minute:02d}:{second:02d}"

	@staticmethod
	def _amount(text):
		"""'4.20' as 4.2. '0.00' is 0.0 - a real charge of nothing, not an absence."""
		clean = (text or "").replace("AED", "").strip()
		if not AMOUNT_RE.match(clean):
			raise ValueError(f"Unreadable amount: {text!r}")
		return float(clean.replace(",", ""))
