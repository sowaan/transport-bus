// Runs inside the Salik customer-portal tab. Reads the toll crossings the
// signed-in account lists on its Transactions page.
//
// **These are charges, not fines.** The rows this returns are posted to their
// own endpoint and land in Toll Crossing - never in the fines route, which
// invoices what it stages.
//
// What makes this reader different from the others:
//
// 1. **It reads the window the page opens on and says so.** Salik defaults to
//    the last 24 hours. Its 7- and 30-day filters have not been seen working
//    (whether they reload the table or navigate the page, which would tear this
//    script down), so none is pressed. The window actually read is reported in
//    the coverage entry instead of being assumed.
//
// 2. **A crossing is two rows and only one needs no click.** The detail row
//    (tag, transaction id, post date, schedule) is in the DOM whether or not it
//    is expanded, so nothing in a row is ever clicked. The one control that IS
//    clicked is `#loadMore` inside the trips container - never the parking
//    tab's button, never anything in the filter form, and never the delink
//    account confirmation that sits elsewhere on the page.
//
// 3. **Every crossing is read or the read is reported partial.** Load more is
//    pressed until it is gone. A click that adds no rows, a repeated
//    transaction id, a row that does not match the expected layout, or a stop at
//    the cap or the deadline with the button still showing, all end the read as
//    unread rather than passing part of the list off as the whole.
//
// 4. **It refuses rather than reporting zero when signed out** - and refuses an
//    Arabic page, whose labels and dates it cannot read.
//
// It never signs in, never types a credential and never answers a challenge:
// the operator does all of that in their own browser.

(() => {
	if (globalThis.__tffSalikLoaded) return;
	globalThis.__tffSalikLoaded = true;

	const { extractRows } = globalThis.PORTAL_EXTRACTORS.salik;

	const POLL_MS = 250;

	// The page is server-rendered but its table is filled by script afterwards.
	const TABLE_GRACE_MS = 60000;

	// One "Load more" is one server request. This is its ceiling.
	const PAGE_GRACE_MS = 45000;

	// How long the row count must stand still, with no loader showing, before a
	// load is considered finished.
	const SETTLE_MS = 1500;

	// Ten crossings a load: this reads up to a thousand, and reports a longer
	// list as partial rather than reading on without limit.
	const MAX_LOADS = 100;

	// Kept back from the background's read budget so the answer still reaches it.
	const BUDGET_MARGIN_MS = 10000;
	const DEFAULT_BUDGET_MS = 20 * 60 * 1000;

	const CONTAINER = "#trips-container";
	const LIST = "Salik toll crossings";

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

	const visible = (el) => !!el && el.getClientRects().length > 0 && getComputedStyle(el).visibility !== "hidden";

	/** Whether the account is signed in, judged on the page's own evidence.
	 *
	 * The sign-out link is only drawn for a signed-in account. And the page keeps
	 * several "You've been logged out" boxes in its markup permanently, hidden -
	 * so their TEXT proves nothing; only one being visible does.
	 */
	const signedIn = () =>
		!!document.querySelector('a[href*="connect/signout"]') &&
		![...document.querySelectorAll(".signedOutBox")].some(visible);

	const onLoginPage = () => /\/connect\/|\/login/i.test(location.pathname);

	const container = () => document.querySelector(CONTAINER);
	const loading = () => !!document.querySelector(`${CONTAINER} .db-loader`);

	/** The "Load more" control for crossings, or null once there is nothing more.
	 *
	 * Looked up inside the trips container because the page has a second tab with
	 * its own button; and required to be visible and enabled, since the page
	 * removes or hides it when the list is exhausted.
	 */
	function loadMore() {
		const button = document.querySelector(`${CONTAINER} #loadMore`);
		return button && visible(button) && !button.disabled ? button : null;
	}

	const rowCount = () => document.querySelectorAll(`${CONTAINER} table.toll-trips-table tr.open`).length;

	/** The window the filter is set to, so the read says what it covered. */
	function windowShown() {
		const checked = document.querySelector('#FormTrips input[name="filter-hours"]:checked');
		const labels = { 1: "24 hours", 2: "7 days", 3: "30 days" };
		const range = checked ? labels[checked.value] || null : null;
		const start = (document.querySelector("#StartDate") || {}).value || "";
		const end = (document.querySelector("#EndDate") || {}).value || "";
		if (start && end) return `${start} to ${end}`;
		return range;
	}

	/** Waits out a load: no loader showing and the row count steady. */
	async function settle(deadline) {
		let last = -1;
		let since = Date.now();
		for (;;) {
			const now = rowCount();
			if (!loading() && now === last) {
				if (Date.now() - since >= SETTLE_MS) return true;
			} else {
				last = now;
				since = Date.now();
			}
			if (Date.now() > deadline) return false;
			await sleep(POLL_MS);
		}
	}

	/** Every crossing, or null with the reason it could not be read whole. */
	async function readCrossings(deadline, progress) {
		let loads = 0;

		for (;;) {
			const button = loadMore();
			if (!button) break;

			if (loads >= MAX_LOADS) {
				return { rows: null, reason: `more than ${MAX_LOADS * 10} crossings, so the list was read in part` };
			}
			if (Date.now() > deadline) {
				return { rows: null, reason: "the read ran out of time with more crossings still to load" };
			}

			const before = rowCount();
			button.click();
			loads += 1;

			// The count rising, or the button going, means the click did something.
			const moved = await waitFor(() => rowCount() > before || !loadMore(), PAGE_GRACE_MS);
			if (!moved) {
				return { rows: null, reason: `load ${loads} never returned, so the list was read in part` };
			}
			if (!(await settle(deadline))) {
				return { rows: null, reason: "the page was still loading when the read ran out of time" };
			}
			progress({ stage: "reading", message: `Read ${rowCount()} crossing(s)…` });
		}

		const all = extractRows();
		if (all === null) return { rows: null, reason: "the crossings table disappeared part-way through" };

		const bad = all.filter((row) => !row._ok).length;
		if (bad) {
			return {
				rows: null,
				reason: `${bad} row(s) did not match the layout this reader was written to, so none were sent`,
			};
		}

		const missing = all.filter((row) => !row._txn).length;
		if (missing) {
			return { rows: null, reason: `${missing} crossing(s) had no transaction id` };
		}

		const seen = new Set();
		for (const row of all) {
			if (seen.has(row._txn)) {
				return { rows: null, reason: "the list changed while it was being read (a transaction appeared twice)" };
			}
			seen.add(row._txn);
		}

		return { rows: all };
	}

	chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
		if (!message || message.type !== "TFF_READ") return;

		const progress = (payload) => {
			chrome.runtime
				.sendMessage({ type: "TFF_PROGRESS", requestId: message.requestId, ...payload })
				.catch(() => {
					// The desk tab can be closed mid-run. Losing the progress line is
					// not a reason to abandon a read in flight.
				});
		};

		(async () => {
			const budget = Number(message.budgetMs) > 0 ? Number(message.budgetMs) : DEFAULT_BUDGET_MS;
			const deadline = Date.now() + Math.max(0, budget - BUDGET_MARGIN_MS);

			progress({ stage: "reading", message: "Opening the Salik transactions page…" });

			await waitFor(() => signedIn() || onLoginPage(), TABLE_GRACE_MS);

			if (!signedIn()) {
				sendResponse({ ok: false, state: "not-signed-in" });
				return;
			}

			// English only: the column labels, the date and the "Toll Schedule"
			// text are all matched in English.
			const lang = (document.documentElement.lang || "").toLowerCase();
			if (lang && !lang.startsWith("en")) {
				sendResponse({
					ok: false,
					state: "error",
					message:
						"The Salik page is not in English, and this reader can only read the English " +
						"page. Switch the page language to English and press the button again. " +
						"Nothing was read.",
				});
				return;
			}

			// Wait for the table, or for the page's own empty message with no
			// loader showing - never judge an unfinished page.
			const ready = await waitFor(() => {
				if (!container()) return false;
				if (loading()) return false;
				return extractRows() !== null;
			}, TABLE_GRACE_MS);
			if (!ready) {
				sendResponse({ ok: false, state: "no-table" });
				return;
			}

			await settle(deadline);

			const window = windowShown();
			const { rows, reason } = await readCrossings(deadline, progress);

			// Signing out mid-read would leave a short list looking complete.
			if (!signedIn()) {
				sendResponse({ ok: false, state: "not-signed-in" });
				return;
			}

			const coverage = [{ list: LIST, read: rows ? rows.length : null, reason: reason || null, window }];

			sendResponse({
				ok: true,
				state: "read",
				rows: rows || [],
				truncated: rows === null,
				coverage,
			});
		})().catch((error) => {
			sendResponse({ ok: false, state: "error", message: String(error && error.message) });
		});

		// Keeps the message channel open for the async work above.
		return true;
	});
})();
