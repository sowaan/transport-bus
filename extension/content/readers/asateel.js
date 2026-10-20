// Runs inside the Asateel (ITC) tab. Reads the vehicle permit registry the
// signed-in account lists on its Manage Vehicles page.
//
// **This is a permit registry, not a fines page.** The rows this returns are
// posted to their own endpoint, which records an expiry date on each vehicle -
// never to the fines route, which invoices what it stages.
//
// Four principles, the same as the other readers:
//
// 1. **Nothing in a row is clicked.** The one control this presses is the
//    pager's "next page" arrow. Not the select boxes, not a row's actions menu,
//    not Export, not the filter's Apply.
//
// 2. **Every vehicle is read or the read is reported partial.** The pager is
//    followed until its next arrow is gone, and the count is then checked against
//    the page's own "Total Vehicles" tile. A page that never turns, a page that
//    shows the same vehicles again, a row that does not match the layout, or a
//    stop at the cap or deadline all end the read as unread rather than passing
//    part of the fleet off as the whole.
//
// 3. **It refuses rather than reporting zero when signed out** - and refuses a
//    page whose column labels are not the English ones it was written against
//    (the Arabic page, or a re-themed one).
//
// 4. **It does not wait on a spinner.** The page's loading indicator has not been
//    seen, so a turned page is recognised by what the table shows: the pager
//    moved on by one, the vehicles listed changed, and the rows then held still.
//    "The vehicles listed" means their PLATES. The Traffic Code column is the
//    company's traffic file number - the same on every row of the client's
//    account - so it cannot tell one page from the next. Comparing it is what
//    made every live read stop at page 2.
//
// It never signs in, never types a credential and never answers a challenge:
// the operator does all of that in their own browser.

(() => {
	if (globalThis.__tffAsateelLoaded) return;
	globalThis.__tffAsateelLoaded = true;

	const { extractRows, nextPage } = globalThis.PORTAL_EXTRACTORS.asateel;

	const POLL_MS = 250;

	// The app draws its shell first and fills the table once its data call returns.
	const SIGNIN_GRACE_MS = 45000;
	const TABLE_GRACE_MS = 60000;

	// One page turn is one server request. This is its ceiling.
	const PAGE_GRACE_MS = 45000;

	// How long the rows must stand still before a page is considered drawn.
	const SETTLE_MS = 1500;

	// Ten vehicles a page: this reads up to two thousand and reports a longer
	// fleet as partial rather than reading on without limit.
	const MAX_PAGES = 200;

	// Kept back from the background's read budget so the answer still reaches it.
	const BUDGET_MARGIN_MS = 10000;
	const DEFAULT_BUDGET_MS = 20 * 60 * 1000;

	const LIST = "Asateel vehicle permits";

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

	/** Whether the account is signed in: the app draws a Log Out link only then. */
	const signedIn = () => !!document.querySelector('a[href$="/logout"]');

	/** The pager's current page number, or null when there is no pager. */
	function activePage() {
		const active = document.querySelector("ul.pagination li.page-item.active");
		const n = active ? parseInt((active.textContent || "").trim(), 10) : NaN;
		return Number.isNaN(n) ? null : n;
	}

	/** One vehicle row as a comparable string. The plate says which vehicle it is. */
	const rowKey = (row) => [row._emirate, row._code, row._number, row._domain, row._permit, row._status].join("/");

	/** What the table shows, as one comparable string - every row, not a sample. */
	function shown() {
		const rows = extractRows();
		if (!rows || !rows.length) return "";
		return rows.map(rowKey).join("|");
	}

	/**
	 * How many vehicles the list itself says it holds, or null. The table is drawn
	 * with its server-side count as an attribute; unlike the "Total Vehicles"
	 * tile, it counts only this list - this tab, with any filter that is on.
	 */
	function listTotal() {
		const table = document.querySelector(".v-data-table[total]");
		const n = table ? parseInt(table.getAttribute("total"), 10) : NaN;
		return Number.isNaN(n) ? null : n;
	}

	/** The number the page's own tile gives for a label, or null if no such tile. */
	function tile(label) {
		for (const box of document.querySelectorAll(".left-content")) {
			const title = box.querySelector(".title");
			if (!title || (title.textContent || "").trim() !== label) continue;
			const value = box.querySelector(".value");
			const n = value ? parseInt((value.textContent || "").replace(/[,\s]/g, ""), 10) : NaN;
			return Number.isNaN(n) ? null : n;
		}
		return null;
	}

	/** Waits until what the table shows has held still. */
	async function settle(deadline) {
		let last = null;
		let since = Date.now();
		for (;;) {
			const now = shown();
			if (now && now === last) {
				if (Date.now() - since >= SETTLE_MS) return true;
			} else {
				last = now;
				since = Date.now();
			}
			if (Date.now() > deadline) return false;
			await sleep(POLL_MS);
		}
	}

	/** What the page looked like when a turn did not land, so the report says why. */
	function pageState(before, turnedFrom) {
		const now = shown();
		const next = document.querySelector('ul.pagination button[aria-label="Go to next page"]');
		return [
			`pager on page ${activePage()} (was ${turnedFrom})`,
			!now ? "table empty or gone" : now === before ? "table still shows the same vehicles" : "table changed",
			next ? "next arrow still present" : "next arrow gone",
			document.querySelector(".v-progress-linear, .v-overlay--active, .spinner-border, .loading")
				? "a loading indicator is showing"
				: "no loading indicator",
		].join("; ");
	}

	/**
	 * The vehicles read, and the reason the list is not whole (null when it is).
	 * A read that stops early still returns what it got: a permit expiry only ever
	 * moves forward and writing it twice changes nothing, so ten good rows are
	 * worth keeping, and the reason is what stops them passing for the whole fleet.
	 */
	async function readVehicles(deadline, progress) {
		const all = [];
		const seen = new Set();
		let pages = 0;
		let repeated = 0;

		for (;;) {
			if (!(await settle(deadline))) {
				return { rows: all, reason: "the page was still changing when the read ran out of time" };
			}

			const rows = extractRows();
			if (rows === null) return { rows: all, reason: "the vehicles table disappeared part-way through" };

			const bad = rows.filter((row) => !row._ok).length;
			if (bad) {
				return {
					rows: all,
					reason: `${bad} row(s) on page ${pages + 1} did not match the layout this reader was written to, so that page and the rest were not read`,
				};
			}

			// A page made only of vehicles already read means the pager served an
			// earlier page again. A few repeats on an otherwise new page do not: a
			// list sorted on a column many rows share can shift a vehicle across a
			// page boundary. Those are skipped, and the count check below catches any
			// vehicle the shift pushed off the list instead.
			const fresh = rows.filter((row) => !seen.has(rowKey(row)));
			if (!fresh.length) {
				return {
					rows: all,
					reason: `page ${pages + 1} listed only vehicles already read, so the pager did not turn the page it seemed to`,
				};
			}
			repeated += rows.length - fresh.length;
			for (const row of fresh) {
				seen.add(rowKey(row));
				all.push(row);
			}
			pages += 1;
			progress({ stage: "reading", message: `Read ${all.length} vehicle(s)…` });

			if (pages >= MAX_PAGES) {
				return { rows: all, reason: `more than ${MAX_PAGES * 10} vehicles, so the list was read in part` };
			}
			if (Date.now() > deadline) {
				return { rows: all, reason: "the read ran out of time with more pages still to read" };
			}

			const before = shown();
			const turnedFrom = activePage();
			// No next arrow left means this was the last page.
			if (!nextPage()) break;

			// The pager moves at once; the rows follow when the server answers. Both
			// have to change - and the pager by exactly one - before the page counts
			// as turned. Where there is no numbered pager, the rows alone decide.
			const landed = () => {
				const now = shown();
				if (!now || now === before) return false;
				return turnedFrom === null || activePage() === turnedFrom + 1;
			};
			const moved = await waitFor(landed, PAGE_GRACE_MS);
			if (!moved) {
				return { rows: all, reason: `page ${pages + 1} never loaded, so the list was read in part (${pageState(before, turnedFrom)})` };
			}
		}

		const repeats = repeated ? ` (${repeated} repeated row(s) across pages were skipped)` : "";

		// The list states its own count. A pager that skipped a page, or a vehicle
		// pushed off by a shifting sort, shows up here as a short count.
		const expected = listTotal();
		if (expected !== null && expected !== all.length) {
			return { rows: all, reason: `read ${all.length} vehicle(s) but the list says it holds ${expected}${repeats}` };
		}

		// The tile counts the whole fleet: both tabs, and no filter. A list read
		// whole that is still shorter means a filter was left on, or the rest are
		// under Hired Vehicles - either way not the whole fleet.
		const fleet = tile("Total Vehicles");
		if (fleet !== null && fleet !== all.length) {
			return {
				rows: all,
				reason:
					`read all ${all.length} vehicle(s) in the list shown, but the page counts ${fleet} in all - ` +
					`a filter may be on, or the rest are under the Hired Vehicles tab${repeats}`,
			};
		}

		return { rows: all, reason: null };
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

			progress({ stage: "reading", message: "Opening the Asateel vehicles page…" });

			await waitFor(signedIn, SIGNIN_GRACE_MS);
			if (!signedIn()) {
				sendResponse({ ok: false, state: "not-signed-in" });
				return;
			}

			// Wait for the first rows. A table that stays empty is not read as an
			// empty fleet unless the page itself says there are no vehicles.
			const drawn = await waitFor(() => {
				const rows = extractRows();
				return rows && rows.length > 0;
			}, TABLE_GRACE_MS);
			if (!drawn) {
				const fleet = tile("Total Vehicles");
				if (extractRows() !== null && fleet === 0) {
					sendResponse({
						ok: true,
						state: "read",
						rows: [],
						truncated: false,
						coverage: [{ list: LIST, read: 0, reason: null, window: null }],
					});
					return;
				}
				// An empty list on a fleet that has vehicles: a filter, or the wrong tab.
				if (extractRows() !== null && listTotal() === 0 && fleet) {
					sendResponse({
						ok: true,
						state: "read",
						rows: [],
						truncated: true,
						coverage: [{
							list: LIST,
							read: 0,
							reason: `the list shown is empty but the page counts ${fleet} vehicle(s) - a filter may be on, or they are under the Hired Vehicles tab`,
							window: null,
						}],
					});
					return;
				}
				sendResponse({ ok: false, state: "no-table" });
				return;
			}

			// The first row fails the layout check when the column labels are not the
			// expected English ones - say so, rather than the vaguer partial-read note.
			const first = extractRows()[0];
			if (!first._ok) {
				sendResponse({
					ok: false,
					state: "error",
					message:
						"The Asateel page does not look the way this reader expects: the column " +
						"labels are not the English ones it was written against, or a vehicle's " +
						"plate or traffic code could not be read. If the page is in Arabic, switch " +
						"it to English and press the button again. Nothing was read.",
				});
				return;
			}

			const { rows, reason } = await readVehicles(deadline, progress);

			// Signing out mid-read would leave a short list looking complete.
			if (!signedIn()) {
				sendResponse({ ok: false, state: "not-signed-in" });
				return;
			}

			sendResponse({
				ok: true,
				state: "read",
				rows,
				truncated: !!reason,
				coverage: [{ list: LIST, read: rows.length, reason: reason || null, window: null }],
			});
		})().catch((error) => {
			sendResponse({ ok: false, state: "error", message: String(error && error.message) });
		});

		// Keeps the message channel open for the async work above.
		return true;
	});
})();
