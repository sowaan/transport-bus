# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

"""Abu Dhabi Mobility / DARB — the toll platform, darb.qmobility.ae.

**Read in the operator's own browser, after they have signed in.** The fines
pages were captured signed in on 2026-09-20; before that this module existed
only to refuse, and the refusal is now replaced by a reader.

**Scope first, because it decides what these rows mean.** DARB is the Abu
Dhabi road-toll platform, and its fines page carries two separate lists:

    Traffic Toll    toll violations - unregistered vehicle, insufficient
                    balance, gate manipulation
    Mawaqif Fines   Abu Dhabi parking violations

Neither is the police traffic-fine registry. Exactly as with `srta.py`, a clean
result here says nothing about a vehicle's police fines, and the two must never
be summed into one liability without explicit reconciliation. Both lists are
read, and every row records which one it came from, because they are different
debts to different authorities.

**Why the server cannot do this.** Two challenges sit in front of the fines,
either sufficient on its own: a bot-management layer answers anything that is
not a browser with a 403 - a plain request for the page or its bundle still
fails today - and DARB's own login form carries a visible reCAPTCHA v2. The
standing policy is to stop at bot detection, never to evade it. The operator
signs in themselves, answering their own challenge, and the extension reads the
page that results. That is the TAMM arrangement and it is the only one
available here.

**The session lives in localStorage** (`USER_TOKEN`, `CURRENT_USER`), not in
sessionStorage and not in a cookie the reader can see. Measured, because it
decides whether this portal is readable at all: localStorage is shared across
tabs of the same origin, so a tab the extension opens **inherits the operator's
sign-in**. Verified by opening a second tab and landing straight on the fines
page. Had the token been in sessionStorage - which is per-tab - the extension
could never have read this portal without driving the operator's own tab.

**THE LANDMINE, and the reason `client_fetch_target` points at the app root
rather than at a fines page.** There are two fines routes -
`establishment-fines` for company accounts and `individual-fines` for personal
ones - and **navigating to the one that does not match the signed-in account
does not merely fail. It destroys the session**: `USER_TOKEN` and
`CURRENT_USER` are cleared from localStorage and the tab is bounced to the
login form, signing the operator out of every other tab as well. Measured on
2026-09-20 by doing exactly that to an individual account.

Nothing on the server knows which kind of account the operator holds, so a
server that named a fines route would be guessing, and half its guesses would
log the operator out. Instead the tab is opened on `/RucWeb/`, which is valid
for every account, and the reader reads `IS_ESTABLISHMENT` from localStorage
and clicks the matching in-app link. A click is an Angular route change rather
than a page load, so the reader survives it - a hard navigation would tear the
content script down mid-run.

**What was verified against real rows**, on a signed-in account:

* Both lists fill themselves in without a search to submit or a tab to click -
  the hidden list is populated too, which is why both are read without
  touching the tab strip. (Each fetches after the page mounts, behind its own
  loader; see the template notes below.)
* Column order for both lists, read off the live `<thead>`.
* **Every `<td>` contains a hidden `<span class="ui-column-title">` holding a
  copy of the column header**, which PrimeNG renders for its mobile layout. A
  plain `textContent` read returns the header glued to the value - "Payment
  StatusPaid" - so the extractor strips it. This was measured, not guessed:
  raw cell lengths ran up to 19 characters longer than the real value.
* The plate is a `<vehicle-plate>` component that exposes its three parts
  separately, so unlike RAKTA nothing has to be stamped on from the query.
* Payment status is a `div.badge`, with the state also carried in a
  `badge-success` / `badge-danger` modifier class.
* Status vocabulary seen: `Paid`, `Unpaid`.
* Dates render `%d/%m/%Y %H:%M:%S`, and **day-first is proven rather than
  assumed** - a first component of 30 was observed, which can only be a day.

**What DARB's own compiled templates prove**, read on 2026-10-09 out of the
production bundle the app ships (`main-es2015.c558973e116f48786b94.js`). This
is DARB's source of truth for the markup, so it settles what a single live
account could not - but it is the template, not a rendered page, and the
caveats below say where that difference still matters.

* **Both fines routes render one component.** `individual-fines` and
  `establishment-fines` both mount `app-fines-parent`, a two-panel tab view
  holding `owner-fines` (Traffic Toll) and `mawaqif-fines`. Only the route
  guard differs - which is THE LANDMINE above - so the company layout is the
  personal one.
* **The Traffic Toll row is twelve `<td>`s**, in this order: selection
  checkbox, ReferenceNumber, BrandLogo, PlateNumber, CreationFineDate,
  DateTime, Description, PaymentStatus, FineAmount, AmountAfterDiscount, and
  two action cells. That is the column map below, now proven rather than read
  off a header row. Mawaqif's ten match what the live rows showed in
  September; its Description cell is one of two language-specific cells of
  which exactly one renders.
* **BrandLogo is an image and nothing else**, so its text is always empty. The
  make is recovered from the image's file name instead.
* **The badge's colour class is bound to the fine's paid flag** in both lists -
  `isPaid ? "badge-success" : "badge-danger"` - while its text goes through
  the translation pipe. The class is therefore the reliable signal, and it
  holds whichever language the operator last chose.
* **A frozen Traffic Toll fine** carries a second span inside the badge, keyed
  "NotPayable", rendered only when the fine is frozen. **A Mawaqif fine the
  operator cannot pay** has no selection checkbox: that cell renders only
  when the fine is both unpaid and payable.
* **AmountAfterDiscount falls back to the face amount** when there is no
  discount (`amountAfterDiscount || amount`), so an equal figure means no
  discount was offered and is recorded as none.
* **Dates** use the app-wide `dd/MM/yyyy HH:mm:ss`, shown in UAE time.
* **Each list mounts empty and loads afterwards.** Its table renders the "No
  Records" placeholder first, its component raises a loader
  (`div.loadingAber`) while the request is out, and the rows land with the
  answer. A request that fails on DARB's side clears the loader and leaves
  the placeholder - the same picture as a list with no fines. So the reader
  waits for every loader to clear, and cross-checks each list against its
  own "Total Pending Fines" card, which comes from a separate request.
* **Pagination is exact, and it changes what "no paginator" means.** Both
  tables are lazy, server-paged PrimeNG tables whose paginator is bound to
  `totalCount > gridPageSize`, and `gridPageSize` is 10. So a list with no
  paginator has rendered every fine it has - which retroactively confirms the
  September read of exactly ten - and a list with a paginator has more fines
  than are on screen. The reader walks the pages; see `readers/darb.js`.

**What is still NOT verified, and must not be presented as though it were:**

* **A rendered, populated Traffic Toll row.** The template fixes the cells and
  their order; no live row has been seen. The English text of its status is
  inferred rather than observed: it uses the same translation key as Mawaqif,
  whose live rows read "Paid" and "Unpaid".
* **A live page walk, or a live slow load.** Paging and the loading wait were
  tested against a stand-in page built to the compiled template, not against
  DARB. In particular, clicking next on the
  Mawaqif table while its tab panel is hidden has not been exercised on the
  real app. The walk refuses rather than guesses: any page that fails to load,
  comes back short before the last page, or repeats a fine already read
  marks that list unread. Still, the first real run on a list longer than ten
  should be checked by hand against the portal.
* **The establishment account's data.** Same component, so the same markup -
  but no company account has been signed into.
"""

import re

from transport.transport.fine_sync.base import FetchedFine, FineFetcher, FineFetchError

# The app root, deliberately. See THE LANDMINE above: naming a fines route
# would be a guess, and a wrong guess signs the operator out.
APP_URL = "https://darb.qmobility.ae/RucWeb/"

# Recorded so nobody has to enumerate the route table again. NOT used as a
# navigation target by the server - the reader picks between them.
FLEET_FINES_PATH = "/RucWeb/establishment-fines"
INDIVIDUAL_FINES_PATH = "/RucWeb/individual-fines"

# Whether a fine is paid, read from the badge text. A FALLBACK only: the
# extractor reads the badge's colour class first, because the template binds
# that class to the paid flag while the text goes through translation. The
# text is consulted when the class is missing, and English is the only
# language it can be read in. "UnPaid" is the template's untranslated key.
PAID_BY_STATUS_TEXT = {
	"Paid": True,
	"Unpaid": False,
	"UnPaid": False,
}

# Where DARB's brand-logo file names start, ahead of the make. A logo that does
# not follow the pattern - the app's default image, say - yields no make
# rather than a file name posing as one.
MAKE_IMAGE_PREFIX = "UTS_VEHICLE_MAKE_"

AMOUNT_RE = re.compile(r"-?\d[\d,]*\.?\d*")

# Both fines tables, read positionally.
#
# **Keyed on cell count, not on header text.** The two lists have different
# column counts - twelve and ten - which makes the count a clean discriminator,
# and it is the only one that survives the language toggle: these headers are
# rendered through a translation pipe, so their text is Arabic whenever the
# operator last chose Arabic. Column ORDER does not change with language.
#
# The same property makes the empty state safe to detect. An empty list renders
# a single cell reading "No Record Found" - the text is translated, the shape is
# not, so a row with too few cells is the placeholder in any language.
EXTRACT_ROWS_JS = """() => {
  const tables = [...document.querySelectorAll('p-table table')];
  if (!tables.length) return null;

  // cell count -> which list it is, and where each value sits in the row.
  // Both column maps are DARB's compiled row templates, cell for cell.
  //
  // `payable` names how each list says a fine cannot be paid right now, and
  // the two genuinely differ: Traffic Toll adds a "NotPayable" marker inside
  // the badge when a fine is frozen, while Mawaqif simply omits the selection
  // checkbox - it renders that only for a fine that is unpaid AND payable.
  const LISTS = {
    12: { list: 'Traffic Toll', payable: 'marker',
          cols: { ticket: 1, logo: 2, plate: 3, issued: 4, when: 5,
                  description: 6, status: 7, amount: 8, discounted: 9 } },
    10: { list: 'Mawaqif',      payable: 'checkbox',
          cols: { ticket: 1, description: 2, plate: 3, when: 4, area: 5,
                  sector: 6, status: 7, amount: 8 } },
  };

  // The paid flag, from the badge's colour class. DARB's template binds that
  // class directly to the fine's paid flag, while the badge TEXT goes through
  // the translation pipe - so the class holds in Arabic and the text does not.
  // null when neither class is present: unknown, never guessed.
  const paidOf = (badge) => {
    if (!badge) return null;
    if (badge.classList.contains('badge-success')) return true;
    if (badge.classList.contains('badge-danger')) return false;
    return null;
  };

  // PrimeNG renders a hidden copy of the column header inside every cell for
  // its mobile layout. Reading textContent without removing it returns the
  // header welded to the value.
  const text = (td) => {
    if (!td) return '';
    const copy = td.cloneNode(true);
    copy.querySelectorAll('.ui-column-title').forEach((n) => n.remove());
    return (copy.textContent || '').replace(/\\s+/g, ' ').trim();
  };

  // The plate is a component, not a string, and it hands over its three parts
  // already separated - which is what lets the server match a vehicle without
  // parsing anything.
  const plateOf = (td) => {
    const vp = td && td.querySelector('vehicle-plate');
    if (!vp) return { code: '', emirate: '', number: '', text: text(td) };
    const part = (sel) => {
      const el = vp.querySelector(sel);
      return el ? (el.textContent || '').replace(/\\s+/g, ' ').trim() : '';
    };
    // The emirate element holds the name more than once; the inner span is the
    // single clean copy, and the outer text is the fallback if that moves.
    const inner = vp.querySelector('.emritsName span');
    return {
      code: part('.platePrefix'),
      emirate: inner ? (inner.textContent || '').trim() : part('.emritsName'),
      number: part('.plateNumber'),
      text: text(td),
    };
  };

  const out = [];
  for (const table of tables) {
    const headers = [...table.querySelectorAll('thead th')]
      .map((th) => (th.textContent || '').replace(/\\s+/g, ' ').trim());

    for (const tr of table.querySelectorAll('tbody tr')) {
      const cells = [...tr.children];
      const spec = LISTS[cells.length];
      // The empty-list placeholder, or a shape this build does not know.
      // Skipped rather than guessed at.
      if (!spec) continue;

      const c = spec.cols;
      const plate = plateOf(cells[c.plate]);
      const badge = cells[c.status] ? cells[c.status].querySelector('.badge') : null;
      const paid = paidOf(badge);

      // The status word is the badge's FIRST span. Reading the whole badge
      // would weld a frozen fine's "NotPayable" marker onto it.
      const word = badge ? badge.querySelector('span') : null;
      const status = word
        ? (word.textContent || '').replace(/\\s+/g, ' ').trim()
        : badge ? (badge.textContent || '').replace(/\\s+/g, ' ').trim() : text(cells[c.status]);

      let notPayable = null;
      if (spec.payable === 'marker') {
        // Frozen: a second span inside the badge.
        const frozen = !!badge && badge.querySelectorAll('span').length > 1;
        notPayable = frozen ? true : (paid === null ? null : false);
      } else if (spec.payable === 'checkbox') {
        // Meaningful only for an unpaid fine - a paid one has no checkbox either.
        const box = cells[0] && cells[0].querySelector('input[type=checkbox]');
        notPayable = paid === false ? !box : (paid === true ? false : null);
      }

      // The brand cell is an image and nothing else. Its file name is the only
      // place the make survives.
      const img = c.logo === undefined ? null : (cells[c.logo] && cells[c.logo].querySelector('img'));
      const logo = img
        ? (img.getAttribute('src') || '').split(/[?#]/)[0].split('/').pop()
        : '';

      out.push({
        _list: spec.list,
        _ticket: text(cells[c.ticket]),
        _description: text(cells[c.description]),
        _plateCode: plate.code,
        _plateEmirate: plate.emirate,
        _plateNumber: plate.number,
        _plateText: plate.text,
        _issued: c.issued === undefined ? '' : text(cells[c.issued]),
        _when: text(cells[c.when]),
        _status: status,
        _paid: paid,
        _notPayable: notPayable,
        // Kept alongside `_paid` so the raw payload shows what it was read from.
        _statusClass: badge ? badge.className : '',
        _amount: text(cells[c.amount]),
        _discounted: c.discounted === undefined ? '' : text(cells[c.discounted]),
        _area: c.area === undefined ? '' : text(cells[c.area]),
        _sector: c.sector === undefined ? '' : text(cells[c.sector]),
        _logo: logo,
        // Carried so a column that moves shows up as a mismatch in the staged
        // payload instead of as quietly wrong values.
        _headers: headers,
      });
    }
  }
  return out;
}"""


class DarbFetcher(FineFetcher):
	"""DARB: both fines lists, read in the operator's signed-in browser."""

	# Two challenges in front of the sign-in, either sufficient on its own.
	# This can never be scheduled.
	supports_unattended = False

	# The server cannot make the request at all - see the module docstring.
	# This is not a missing selector, and no selector will change it.
	fetch_implemented = False

	# UAE Pass is offered, but relaying it would still leave the reCAPTCHA.
	supports_relay = False

	# False for one concrete effect: the tab opens in the FOREGROUND. The
	# operator may not be signed in, and a background tab would leave them
	# staring at a desk dialog while the sign-in they need to answer sat on a
	# tab they could not see.
	#
	# It does NOT buy a longer sign-in window here, although that is what this
	# flag does elsewhere. `path_prefix` is "/RucWeb", and the URL opened is
	# "/RucWeb/", so the extension's landing test passes on the first load
	# whatever page that turns out to be - including the login. The waiting is
	# all done by the reader, which answers "not signed in" within seconds and
	# leaves the operator to sign in and press the button again.
	client_unattended = False

	client_reader = "darb"
	client_origin = "https://darb.qmobility.ae"

	# One extractor and nothing else. There is no detail panel to open, and the
	# pager - which only exists past ten fines - is walked by the reader rather
	# than shipped as NEXT_PAGE_JS: walking it means clicking one table's own
	# next control and waiting on a server round trip for that table, which is
	# reader work. No server fetcher here could ever use a shared copy.
	# Declaring what is actually shipped keeps the generator's drift check
	# meaningful for the portals that do have all three.
	client_extractors = ("EXTRACT_ROWS_JS",)

	def fetch_for_vehicle(self, plate_parts):
		raise FineFetchError(f"{self.portal.name}: {self._server_reason()}")

	def fetch_for_traffic_file(self, traffic_file_number, **kwargs):
		raise FineFetchError(
			f"{self.portal.name} has no traffic-file route. Its fines are listed against the "
			"signed-in account, not against a traffic file."
		)

	@staticmethod
	def _server_reason():
		return (
			"a bot-management layer refuses anything that is not a browser, and DARB's own "
			"sign-in carries a reCAPTCHA. The operator signs in themselves and the extension "
			"reads the page that results."
		)

	def client_fetch_target(self, traffic_file_number=None):
		"""The app root, and deliberately not a fines page.

		`traffic_file_number` is ignored - DARB lists fines against the account,
		not against a traffic file - and the parameter survives only because
		the caller passes it positionally.

		**Nothing identifying is handed over.** There is no prefill, no fleet
		identifier and no plate list: the account the operator is signed into
		already determines what the page shows. That makes this the least
		disclosing of the four client-read portals.

		The URL is the app root because naming a fines route would mean
		guessing the account type, and the wrong guess signs the operator out
		of every tab - see THE LANDMINE in the module docstring. The reader
		reads `IS_ESTABLISHMENT` and clicks its way there instead.
		"""
		return {
			"url": APP_URL,
			"origin": self.client_origin,
			# Everything on this portal lives under /RucWeb, including the
			# login. That is intentional: the tab counts as landed even when
			# the operator is signed out, so the reader gets to run and report
			# "not signed in" rather than the fetch timing out with no reason.
			"path_prefix": "/RucWeb",
			"reader": self.client_reader,
			"unattended": self.client_unattended,
		}

	def _to_fine(self, row):
		"""One row from either fines list as a FetchedFine.

		A row with no reference number is dropped rather than staged under a
		synthetic key: that number is what dedup runs on and what an operator
		types into the portal to find the thing again.
		"""
		ticket = (row.get("_ticket") or "").strip()
		if not ticket:
			return None

		status = (row.get("_status") or "").strip()
		listname = (row.get("_list") or "").strip()
		code = (row.get("_plateCode") or "").strip()
		number = (row.get("_plateNumber") or "").strip()
		emirate = self._emirate(row.get("_plateEmirate"))

		# Traffic Toll prints a discounted figure in its own column; Mawaqif has
		# no such column. Absent stays absent rather than being set equal to the
		# face amount, which would read as a discount offered and declined.
		#
		# And an equal figure IS absent. DARB's template fills that column with
		# `amountAfterDiscount || amount`, so an undiscounted fine shows its face
		# amount twice. Invoicing already ignores a discount that is not below
		# the face amount; storing None says the same thing on the record.
		face = self._amount(row.get("_amount"))
		discounted = self._amount(row.get("_discounted")) if row.get("_discounted") else None
		if discounted is not None and discounted >= face:
			discounted = None

		paid = self._paid(row)

		return FetchedFine(
			ticket_number=ticket,
			amount=face,
			fine_datetime=self._datetime(row.get("_when") or row.get("_issued")),
			fine_type=(row.get("_description") or "").strip() or None,
			# Mawaqif names where it happened; Traffic Toll has no location
			# column at all, so it stays absent rather than being filled with
			# something that is not a location.
			fine_location=self._location(row),
			plate=" ".join(part for part in (emirate, code, number) if part)
			or (row.get("_plateText") or "").strip()
			or None,
			# Neither list reports black points. Zero here means "not
			# reported", and `black_points_reported` records the difference so
			# it is not mistaken for a measured zero.
			black_points=0,
			raw={
				"issuing_authority": "Abu Dhabi Mobility / DARB",
				"face_amount": face,
				"discounted_amount": discounted,
				"plate_emirate": emirate,
				"plate_code": code,
				"plate_number": number,
				"description": (row.get("_description") or "").strip() or None,
				"portal_status": self._portal_status(paid, row.get("_notPayable")),
				# DARB's own word, kept because the mapping above is lossy and
				# because the badge class carries the same state untranslated.
				"darb_payment_status": status or None,
				"darb_status_class": self._badge_state(row.get("_statusClass")),
				"darb_paid": paid,
				# Frozen (Traffic Toll) or not currently payable (Mawaqif). None
				# when the paid state itself could not be read.
				"darb_not_payable": row.get("_notPayable"),
				# Which of the two lists this came from. They are different
				# debts to different authorities and must stay distinguishable
				# after staging.
				"darb_list": listname or None,
				# Which page of that list the row was read from, set by the
				# reader as it walks a paginated list. Kept because a walk is
				# the part of this reader no live list has exercised yet.
				"darb_page": row.get("_page"),
				"vehicle_description": self._make(row.get("_logo")),
				"black_points_reported": False,
				"row": row,
			},
		)

	@staticmethod
	def _paid(row):
		"""True, False, or None when the paid state could not be read.

		The badge's colour class first - the extractor reads it into `_paid`,
		and the template binds it to the paid flag - then DARB's English status
		word for a payload that lacks it.
		"""
		paid = row.get("_paid")
		if paid is True or paid is False:
			return paid
		return PAID_BY_STATUS_TEXT.get((row.get("_status") or "").strip())

	@staticmethod
	def _portal_status(paid, not_payable):
		"""DARB's state as the Portal Status Select: "", "Payable" or "Unpayable".

		Anything unreadable becomes "" rather than a guess: an invalid Select
		value fails the insert and takes the rest of the run down with it, which
		is how RTA's "Non-Payable" once stranded a Failed run holding real staged
		rows. A frozen or otherwise unpayable unpaid fine is "Unpayable", the
		same reading RTA's "Non-Payable" gets - it is owed, but it cannot be paid
		today.
		"""
		if paid is True:
			return "Unpayable"
		if paid is False:
			return "Unpayable" if not_payable else "Payable"
		return ""

	@staticmethod
	def _make(logo):
		"""The vehicle make from DARB's brand-logo file name, or None.

		The brand cell holds only an image, chosen from a make-code map, so the
		file name is where the make survives - "UTS_VEHICLE_MAKE_<MAKE>.png" reads
		as "<MAKE>". Anything off that pattern, such as the app's default logo, is
		None rather than a file name posing as a make.
		"""
		name = (logo or "").strip()
		if not name.upper().startswith(MAKE_IMAGE_PREFIX):
			return None
		make = name[len(MAKE_IMAGE_PREFIX):].rsplit(".", 1)[0]
		return make.replace("_", " ").strip() or None

	@staticmethod
	def _location(row):
		"""Where a Mawaqif fine happened, or None.

		Traffic Toll has no location column, so this is None for every row from
		that list - which is correct, not missing data.
		"""
		parts = [
			(row.get("_area") or "").strip(),
			(row.get("_sector") or "").strip(),
		]
		joined = ", ".join(part for part in parts if part)
		return joined or None

	@staticmethod
	def _badge_state(class_name):
		"""The `badge-*` modifier, which carries the payment state untranslated."""
		for token in (class_name or "").split():
			if token.startswith("badge-"):
				return token
		return None

	@staticmethod
	def _emirate(text):
		"""The plate's emirate as one of our Select options, or None.

		None is a real answer and callers must treat it as "unknown". Passing
		DARB's own wording straight through would put a value in
		`plate_emirate` that no vehicle can hold, which narrows the match to
		nothing instead of widening it to any emirate.
		"""
		from transport.transport.vehicle_plate import normalize_emirate

		return normalize_emirate(text)

	@classmethod
	def _amount(cls, value):
		"""The figure, or 0.0.

		DARB renders the amount and its currency as adjacent elements, so the
		stripped cell reads like "150AED" with no separator. The currency word
		is removed before the number is taken rather than relying on a space
		that is not there.
		"""
		text = (value or "").replace("AED", " ").replace("aed", " ")
		found = AMOUNT_RE.findall(text)
		return float(found[0].replace(",", "")) if found else 0.0

	@staticmethod
	def _datetime(value):
		"""DARB's "dd/mm/yyyy hh:mm:ss" as a Frappe datetime string, or None.

		**Day-first is measured, not assumed** - a first component of 30 was
		observed on a real row, which can only be a day. That is the one thing
		this parser would otherwise be guessing at, and it is the guess that
		silently moves a fine by months for days 1-12.

		Anything that does not match returns None. A fine with no date stages
		and can be corrected; a fine dated today because a parse fell through
		is a liability carrying a false date.
		"""
		from datetime import datetime

		text = (value or "").strip()
		if not text:
			return None
		for fmt in (
			"%d/%m/%Y %H:%M:%S",
			"%d/%m/%Y %H:%M",
			"%d/%m/%Y",
			"%Y-%m-%d %H:%M:%S",
			"%Y-%m-%d",
		):
			try:
				return datetime.strptime(text, fmt).strftime("%Y-%m-%d %H:%M:%S")
			except ValueError:
				continue
		return None
