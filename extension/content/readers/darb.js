// Runs inside the DARB tab. Reads both fines lists the signed-in account shows.
//
// What makes this reader different from the other three:
//
// 1. **It navigates by clicking, never by setting location.** DARB has two
//    fines routes - establishment-fines and individual-fines - and going to
//    the one that does not match the signed-in account CLEARS THE SESSION:
//    USER_TOKEN and CURRENT_USER are wiped from localStorage and every tab is
//    signed out. So the route is chosen from IS_ESTABLISHMENT rather than
//    guessed, and it is reached with a click, which is an Angular route change
//    the content script survives. A hard navigation would tear this script
//    down mid-run even when the route was right.
//
// 2. **There is nothing to submit.** Both lists are already populated when the
//    page renders, including the one behind the inactive tab, so the reader
//    never touches the tab strip and never runs a search.
//
// 3. **It refuses rather than reporting zero when signed out.** The login page
//    lives under the same path prefix, so this script runs there too. Saying
//    "no fines" because nobody was signed in is the one failure that would put
//    a clean bill in front of somebody who owes money.
//
// It never signs in, never types a credential and never answers the reCAPTCHA -
// the operator does all three in their own browser. It never clicks Pay Fines.

(() => {
	if (globalThis.__tffDarbLoaded) return;
	globalThis.__tffDarbLoaded = true;

	const { extractRows } = globalThis.PORTAL_EXTRACTORS.darb;

	const POLL_MS = 250;

	// The Angular app boots after document-complete and neither the navigation
	// nor the tables exist until it has. Same lesson as RTA: a fixed sleep here
	// reports "the portal has changed" when the only thing wrong is that it had
	// not finished drawing.
	const APP_GRACE_MS = 60000;

	// After the fines route is entered, both tables are fetched from the
	// server. This is the ceiling for those requests.
	const TABLES_GRACE_MS = 45000;

	// Both tables arrive independently, so a read taken the moment the first
	// one appears can miss the second. This is how long the row count has to
	// stand still before the page is considered finished.
	const SETTLE_MS = 2000;

	// Where the app records the account type. Shared across tabs, and the only
	// thing standing between this reader and signing the operator out.
	const ESTABLISHMENT_KEY = "IS_ESTABLISHMENT";
	const TOKEN_KEY = "USER_TOKEN";

	const FLEET_FINES = "establishment-fines";
	const INDIVIDUAL_FINES = "individual-fines";

	const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

	async function waitFor(probe, timeoutMs) {
		const started = Date.now();
		for (;;) {
			const found = probe();
			if (found) return found;
			if (Date.now() - started >= timeoutMs) return null;
			await sleep(POLL_MS);
		}
	}

	const read = (key) => {
		try {
			return localStorage.getItem(key);
		} catch {
			return null;
		}
	};

	/** Whether the operator is signed in, judged on the app's own evidence.
	 *
	 * The token, not the absence of a login form: the form is drawn a moment
	 * after the redirect, and a check made in that gap would call a signed-out
	 * tab signed in.
	 */
	const signedIn = () => !!read(TOKEN_KEY);

	const onLoginPage = () => location.pathname.toLowerCase().endsWith("/login");

	/** The fines route this account is allowed to open.
	 *
	 * Returns null when the account type is unreadable, and the caller stops.
	 * Picking one at random is not a fallback here - it is a coin flip where
	 * one side signs the operator out.
	 */
	function finesRouteForAccount() {
		const flag = (read(ESTABLISHMENT_KEY) || "").trim().toLowerCase();
		if (flag === "true") return FLEET_FINES;
		if (flag === "false") return INDIVIDUAL_FINES;
		return null;
	}

	const onFinesRoute = (route) => location.pathname.toLowerCase().includes(route);

	/** Click the in-app link to the fines page. No hard navigation, ever. */
	async function openFines(route) {
		if (onFinesRoute(route)) return true;

		const link = await waitFor(
			() =>
				[...document.querySelectorAll("a[href]")].find((a) => {
					const href = (a.getAttribute("href") || "").toLowerCase();
					return href.endsWith("/" + route) || href.endsWith(route);
				}),
			APP_GRACE_MS
		);
		if (!link) return false;

		link.click();
		return !!(await waitFor(() => onFinesRoute(route), APP_GRACE_MS));
	}

	/** Both tables, once their contents have stopped changing.
	 *
	 * Settled rather than merely present: the two lists are fetched
	 * separately, so reading at first sight of a table can capture one list
	 * and miss the other entirely - which would look like a complete read of
	 * half the debt.
	 */
	async function awaitTables() {
		const appeared = await waitFor(
			() => document.querySelector("p-table table thead th"),
			TABLES_GRACE_MS
		);
		if (!appeared) return false;

		const count = () => document.querySelectorAll("p-table table tbody tr").length;
		let last = count();
		let steadySince = Date.now();
		const deadline = Date.now() + TABLES_GRACE_MS;

		while (Date.now() - steadySince < SETTLE_MS) {
			if (Date.now() > deadline) break;
			await sleep(POLL_MS);
			const now = count();
			if (now !== last) {
				last = now;
				steadySince = Date.now();
			}
		}
		return true;
	}

	// A table is identified by how many columns its header row has. The header
	// row is the part that has been seen for BOTH lists; a populated Traffic
	// Toll body row has not been, which is exactly why identification must not
	// depend on one.
	const LIST_BY_HEADER_COUNT = { 12: "Traffic Toll", 10: "Mawaqif" };

	/** What each rendered list contributed, checked against what it rendered.
	 *
	 * **This is the guard on the one thing about this portal that is still
	 * unverified.** The extractor maps a row's cells by counting them, and only
	 * Mawaqif's count has been confirmed against real rows - the account that
	 * was captured had an empty Traffic Toll list, so its twelve columns are
	 * known from the header alone. If a real Traffic Toll row turns out to
	 * render some other number of cells, the extractor skips every one of them.
	 *
	 * Without this check that lands as `read: 0` - a list reporting no fines -
	 * and the run completes clean over a list full of them. So each table's
	 * rendered rows are counted independently of the extractor, and any
	 * shortfall is reported as `read: null`: unread, which forces `truncated`
	 * and downgrades the run instead of quietly blessing it.
	 */
	function coverageFor(rows) {
		const counts = {};
		for (const row of rows) counts[row._list] = (counts[row._list] || 0) + 1;

		return [...document.querySelectorAll("p-table table")].map((table) => {
			const headerCount = table.querySelectorAll("thead th").length;
			const list = LIST_BY_HEADER_COUNT[headerCount] || `unrecognised (${headerCount} columns)`;

			// The empty-list placeholder is a single cell spanning the table.
			// Anything wider is a row that was meant to carry a fine.
			const rendered = [...table.querySelectorAll("tbody tr")].filter(
				(tr) => tr.children.length > 1
			).length;
			const extracted = counts[list] || 0;

			if (rendered !== extracted) {
				return {
					list,
					read: null,
					reason:
						`${rendered} row(s) are on the page in a shape this build does not ` +
						`recognise, and ${extracted} could be read`,
				};
			}
			return { list, read: extracted };
		});
	}

	chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
		if (!message || message.type !== "TFF_READ") return undefined;

		const progress = (payload) => {
			chrome.runtime
				.sendMessage({ type: "TFF_PROGRESS", requestId: message.requestId, ...payload })
				.catch(() => {
					// The desk tab can be closed mid-run. Losing the progress
					// line is not a reason to abandon a fetch in flight.
				});
		};

		(async () => {
			progress({ stage: "reading", message: "Opening the DARB fines page…" });

			// Give the app a moment to restore a session before judging it -
			// the token is written during bootstrap.
			await waitFor(() => signedIn() || onLoginPage(), APP_GRACE_MS);

			if (!signedIn()) {
				// Not "no fines". The operator signs in and presses the button
				// again; the next tab inherits the session from localStorage.
				sendResponse({ ok: false, state: "not-signed-in" });
				return;
			}

			const route = finesRouteForAccount();
			if (!route) {
				sendResponse({
					ok: false,
					state: "error",
					message:
						"DARB did not say whether this is a company or a personal account, and " +
						"opening the wrong fines page signs you out of every tab. Nothing was " +
						"read and nothing was changed.",
				});
				return;
			}

			if (!(await openFines(route))) {
				sendResponse({ ok: false, state: "no-form" });
				return;
			}

			progress({ stage: "reading", message: "Reading the fines tables…" });

			if (!(await awaitTables())) {
				sendResponse({ ok: false, state: "no-table" });
				return;
			}

			// Signing out mid-read would leave a short list looking complete.
			if (!signedIn()) {
				sendResponse({ ok: false, state: "not-signed-in" });
				return;
			}

			const rows = extractRows();
			if (rows === null) {
				sendResponse({ ok: false, state: "no-table" });
				return;
			}

			const coverage = coverageFor(rows);

			sendResponse({
				ok: true,
				state: "read",
				rows,
				// Set from coverage rather than hardcoded. background.js ORs
				// this with its own `read === null` test, so saying false here
				// would not hide a shortfall - but a reader that reports a
				// partial read as complete is wrong wherever its answer is
				// read, not just where it happens to be double-checked.
				truncated: coverage.some((entry) => entry.read === null),
				coverage,
			});
		})().catch((error) => {
			sendResponse({ ok: false, state: "error", message: String(error && error.message) });
		});

		// Keeps the message channel open for the async work above.
		return true;
	});
})();
