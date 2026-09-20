# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

"""Abu Dhabi Mobility / DARB — the toll platform, darb.qmobility.ae.

**Registered, and deliberately has no reader.** Read this before writing one,
because the missing piece is a signed-in page, not selectors.

**Scope first, because it decides whether this is worth doing at all.** DARB is
the Abu Dhabi road-toll system. Its "fines" are toll and Mawaqif parking
violations - unregistered vehicle, insufficient balance, gate manipulation -
and the route list below separates them from nothing else, because there is
nothing else here. This is NOT the police traffic-fine registry. Exactly as
with `srta.py`, a clean result from DARB says nothing about a vehicle's police
fines, and the two must never be summed into one liability without explicit
reconciliation.

**What was measured on 2026-09-20**, in a real browser on the live site:

* `darb.itc.gov.ae` now redirects to `darb.qmobility.ae`. The host changed with
  the ITC -> Q Mobility rebrand; the path `/RucWeb/login` did not.
* The landing page is a **login**: email / Emirates ID / traffic number plus a
  password, or UAE Pass.
* **A visible reCAPTCHA v2 checkbox sits on that login form.**
* `/RucWeb/establishment-fines` redirects to `/RucWeb/login` when signed out.
* The Angular route table was enumerated in full - **119 routes** - and there
  is no guest or public fines lookup among them. `public-services`, the one
  unauthenticated area, offers a single service: topping up the wallet balance.
* The fines pages are `establishment-fines` (company accounts, which is what a
  fleet would use), `individual-fines`, and Mawaqif parking variants of both.
  All are behind the sign-in.

**This reconciles the earlier capture rather than overturning it.** The portal
record has carried, since 2026-08-22, that a Cloudflare bot-management
challenge blocks the way in and that DARB's own form was never reached. That
still holds for anything that is not a browser: a plain HTTPS request for the
page or its bundle is answered with 403 today. What is new is what sits behind
that layer, which the earlier attempt could not see - and it is a second
challenge, not an open form. So the route is closed twice over, and the
standing policy is unchanged: stop at bot detection, never evade it.

**Why there is no reader here, when RAKTA got one the same week.** RAKTA's
fines form is public, so its markup could be read, a search could be run, and
every assumption in the extractor could be checked against a live result.
DARB's cannot be reached at all without a session. An extractor written from
the bundle alone would be a guess that nobody can test, and `registry.py`
already says what that produces: a reader that finds nothing, and nothing is
indistinguishable from a fleet that owes nothing. A silent zero on a fleet that
owes money is the single worst outcome this package can produce, and it will
not be shipped on an untested selector.

**Leads for whoever does build it - and these are leads, not a contract.**
They come from identifier proximity inside a 10 MB bundle, NOT from a compiled
template read end to end the way `rakta.py`'s six columns were. Treat every one
as unconfirmed until it is seen on a real page:

* The table is PrimeNG, and paginated (`totalRecords`).
* Row-model fragments seen near the fines code: `fineDate`,
  `fineSequenceNumber`, `isPaid`, `plateNumber`, `platePrefix`,
  `plateSourceName`, `lookupPlateSourceCode`, `calculateFineAmount`.
* The fines table's labels resolve through a `Fine.table` translation
  namespace, so the header text is language-dependent. Whatever reads this
  should key on column order or a stable attribute, never on header text -
  the same trap `rakta.py` avoids.

**What would unblock it:** an operator signed in, with the establishment-fines
table on screen, and the `outerHTML` of the table container. From there this
becomes the TAMM arrangement - the person answers their own reCAPTCHA and their
own sign-in, and the extension reads the page that results. Nothing about the
reCAPTCHA prevents that; it prevents a *program* signing in, which is not what
the extension does.
"""

from transport.transport.fine_sync.base import FineFetcher, FineFetchError

LOGIN_URL = "https://darb.qmobility.ae/RucWeb/login"

# The fines pages, recorded so that whoever builds the reader does not have to
# enumerate the route table a second time. Both are behind the sign-in.
FLEET_FINES_PATH = "/RucWeb/establishment-fines"
INDIVIDUAL_FINES_PATH = "/RucWeb/individual-fines"

REASON = (
	"DARB's fines are behind a sign-in that carries its own reCAPTCHA, and the site "
	"answers anything that is not a browser with a bot-management challenge. There is "
	"no guest lookup: its whole public area is a wallet top-up. Nobody has yet seen the "
	"signed-in fines table, so there is nothing to read it with."
)


class DarbFetcher(FineFetcher):
	"""DARB: registered so the refusal names the real blocker."""

	# Two independent challenges, either of which is sufficient on its own.
	supports_unattended = False

	# No reader, and this is what the generator keys on: a module that declares
	# no `client_reader` is skipped entirely, so no extractor constants are
	# demanded of it and none are emitted. It is also what makes
	# `_client_fetch_target` refuse with "no client fetch path" rather than
	# sending a browser somewhere it cannot read.
	client_reader = None

	# The page has never been captured signed in. Until it has, this stays
	# down - the flag exists precisely to stop a portal being offered on the
	# strength of selectors nobody has tested.
	fetch_implemented = False

	# UAE Pass is offered on the login form, but relaying it would still leave
	# the reCAPTCHA, and there is no captured page to read afterwards. False
	# until both of those change.
	supports_relay = False

	def fetch_for_vehicle(self, plate_parts):
		raise FineFetchError(f"{self.portal.name}: {REASON}")

	def fetch_for_traffic_file(self, traffic_file_number, **kwargs):
		raise FineFetchError(f"{self.portal.name}: {REASON}")
