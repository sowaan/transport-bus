// Runs inside the Asateel (ITC) tab. Reads the vehicle permit registry the
// signed-in account lists on its Manage Vehicles page.
//
// **This is a permit registry, not a fines page.** The rows this returns are
// posted to their own endpoint, which records an expiry date on each vehicle -
// never to the fines route, which invoices what it stages.
//
// Four principles, the same as the other readers:
//
// 1. **Only reading controls are pressed.** Reading the list presses only the
//    pager's "next page" arrow. Reading permit numbers (a second step, below)
//    also presses the "Active Permits" tile, a row's three-dot Actions button and
//    its "View Details" item, and goes Back. Never "Change Business Domain", the
//    select boxes, Export, the filter's Apply, or any tab of a vehicle's page.
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

	const { extractRows, nextPage, readDetail } = globalThis.PORTAL_EXTRACTORS.asateel;

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

	/**
	 * Waits ms milliseconds - timed by the extension's service worker, not by this
	 * page. Chrome slows a hidden tab's timers to one tick a second, and after five
	 * minutes hidden to one tick a MINUTE; a read that polls every quarter second
	 * would then take minutes per vehicle the moment the operator looked at the
	 * ERPNext tab to watch its progress. The worker's timers are not throttled,
	 * and its reply arrives as a message, which is not either. If the worker does
	 * not answer (an older build, a severed context) it falls back to a plain
	 * timer for whatever time is left.
	 */
	async function sleep(ms) {
		const started = Date.now();
		try {
			await new Promise((resolve) => {
				chrome.runtime.sendMessage({ type: "TFF_SLEEP", ms }, () => {
					void chrome.runtime.lastError; // read, so Chrome does not log it
					resolve();
				});
			});
		} catch {
			// fall through to the plain timer
		}
		const left = ms - (Date.now() - started);
		if (left > 20) await new Promise((resolve) => setTimeout(resolve, left));
	}

	async function waitFor(probe, timeoutMs) {
		const started = Date.now();
		for (;;) {
			const found = probe();
			if (found) return found;
			if (Date.now() - started >= timeoutMs) return null;
			await sleep(POLL_MS);
		}
	}

	// A note on the page itself, while the permit numbers are being read. The
	// portal's menus are drawn with the browser's frame callbacks, which a hidden
	// tab never gets, so the read needs this tab in front - and the person at the
	// keyboard is the one who can see it is not.
	const BANNER_ID = "tff-asateel-banner";
	function banner(text) {
		let el = document.getElementById(BANNER_ID);
		if (!text) {
			if (el) el.remove();
			return;
		}
		if (!el) {
			el = document.createElement("div");
			el.id = BANNER_ID;
			el.setAttribute(
				"style",
				"position:fixed;left:0;right:0;bottom:0;z-index:2147483647;padding:8px 14px;" +
					"background:#1f3a5f;color:#fff;font:600 13px/1.3 sans-serif;text-align:center;" +
					"pointer-events:none"
			);
			(document.body || document.documentElement).appendChild(el);
		}
		el.textContent = text;
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
	 * Presses the pager's next arrow and waits for the next page to be drawn.
	 * "turned", "last" when there is no next arrow, or what the page looked like
	 * when the turn did not land.
	 *
	 * The pager moves at once; the rows follow when the server answers. Both have
	 * to change - and the pager by exactly one - before the page counts as turned.
	 * Where there is no numbered pager, the rows alone decide.
	 */
	async function turnPage() {
		const before = shown();
		const turnedFrom = activePage();
		if (!nextPage()) return "last";
		const landed = () => {
			const now = shown();
			if (!now || now === before) return false;
			return turnedFrom === null || activePage() === turnedFrom + 1;
		};
		if (await waitFor(landed, PAGE_GRACE_MS)) return "turned";
		return pageState(before, turnedFrom);
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

			const turn = await turnPage();
			// No next arrow left means this was the last page.
			if (turn === "last") break;
			if (turn !== "turned") {
				return { rows: all, reason: `page ${pages + 1} never loaded, so the list was read in part (${turn})` };
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

	// -- permit numbers: the vehicle detail pages ----------------------------
	//
	// The list has no permit number; each vehicle's detail page does. It is
	// reached the way a person reaches it - the row's three-dot Actions menu,
	// "View Details" - and left with the browser's Back. Seen in the client's
	// screen recording (2026-10-23), not in any saved page: the menu is drawn
	// only when opened. So every step waits on something it can see (the menu
	// item, the detail route and its permit card, the list's rows standing
	// still), never on a fixed pause, and anything unexpected ends that vehicle
	// - it keeps what the list said - rather than being clicked through.
	//
	// What the recording showed, and this is built around:
	// * The menu has exactly two items, "View Details" and "Change Business
	//   Domain". Only an element whose text starts "View Details" and does not
	//   also hold "Change Business Domain" is ever clicked.
	// * Back lands on page 1 of the UNFILTERED list, after "Loading items...".
	// * The "Active Permits" tile filters the list to vehicles with an active
	//   permit (about twenty, two pages), so each trip back costs one click.
	//   Whether it took is checked - every row shown has an active permit - and
	//   if it did not, the unfiltered list is walked instead.

	const DETAIL_LIST = "Asateel permit numbers";
	const DETAIL_GRACE_MS = 45000;
	const MENU_GRACE_MS = 8000;
	const ACTIVE_RE = /^\d+ Days?\b/;

	// List rows from the last read, kept for the detail pass that follows it.
	let lastRows = null;

	// What the permit-number pass is doing right now, in words. Sent with every
	// heartbeat, so the desk dialog says WHERE a slow vehicle is, not just that
	// one is slow.
	let doing = "";

	// How long a vehicle waits for this tab to be shown before it is given up on.
	const FRONT_MS = 120000;

	// How often the pass reports in. The extension's service worker is shut down
	// by Chrome after thirty seconds without an event; a vehicle that takes
	// longer than that between two progress lines would otherwise take the whole
	// fetch with it, silently, and nothing read so far would reach ERPNext.
	const HEARTBEAT_MS = 8000;

	// One vehicle's visit is given this long in all; past it the vehicle is
	// given up on, named in the summary, and the pass goes on to the next.
	const VEHICLE_MS = 90000;

	const rowKeyOf = (row) => [row._emirate, row._code, row._number].join(" ");
	const onDetailPage = () => /\/tpc-portal\/manage-vehicle\/detail\/\d+/.test(location.pathname);
	const onListPage = () => /\/tpc-portal\/manage-vehicle\/?$/.test(location.pathname);

	const visible = (el) => !!(el && el.getClientRects().length);
	const textOf = (el) => (el ? el.textContent : "").replace(/\s+/g, " ").trim();

	/** The table's vehicle rows as [tr, row] pairs, in the order extractRows reads them. */
	function rowElements() {
		const table = document.querySelector(".v-data-table table");
		const rows = extractRows();
		if (!table || !rows) return [];
		const trs = [...table.querySelectorAll("tbody tr")].filter((tr) => {
			if ((tr.className || "").includes("expanded")) return false;
			const cells = [...tr.children];
			return !(cells.length === 1 && cells[0].hasAttribute("colspan"));
		});
		// Pairing by position is only safe when both counted the same rows.
		if (trs.length !== rows.length) return [];
		return trs.map((tr, i) => [tr, rows[i]]);
	}

	/** The header tile with this title, as the element a person clicks. */
	function tileCard(label) {
		for (const box of document.querySelectorAll(".left-content")) {
			const title = box.querySelector(".title");
			if (title && textOf(title) === label) return box.closest(".v-card, .custom-card") || box;
		}
		return null;
	}

	/** Back on the list, its rows drawn and still. */
	async function backToList(deadline) {
		if (onDetailPage()) history.back();
		const drawn = await waitFor(() => onListPage() && shown(), Math.min(DETAIL_GRACE_MS, Math.max(0, deadline - Date.now())));
		if (!drawn) return false;
		return settle(deadline);
	}

	/**
	 * Filters the list to active permits with the tile. True when the list shown
	 * afterwards is made only of active-permit vehicles.
	 */
	async function filterToActive(deadline) {
		const allActive = () => {
			const rows = extractRows();
			return !!(rows && rows.length && rows.every((row) => ACTIVE_RE.test(row._permit)));
		};
		if (allActive()) return true;
		const card = tileCard("Active Permits");
		if (!card) return false;
		const before = shown();
		card.click();
		// The list blanks ("Loading items...") and redraws; wait for it to change
		// and then stand still. A tile that does nothing is caught by the check.
		await waitFor(() => shown() && shown() !== before, Math.min(PAGE_GRACE_MS, Math.max(0, deadline - Date.now())));
		if (!(await settle(deadline))) return false;
		return allActive();
	}

	/** Walks the list from where it is to the first row still to be read. */
	async function findPending(pending, deadline) {
		for (let page = 0; page < MAX_PAGES; page += 1) {
			const match = rowElements().find(([, row]) => pending.has(rowKeyOf(row)));
			if (match) return match;
			if (Date.now() > deadline) return null;
			const turn = await turnPage();
			if (turn !== "turned") return null;
			if (!(await settle(deadline))) return null;
		}
		return null;
	}

	/** The "View Details" item of the open Actions menu, or why there is not exactly one. */
	function viewDetailsItem() {
		const hits = [];
		for (const el of document.querySelectorAll("body *")) {
			if (el.closest(".v-data-table")) continue;
			const t = textOf(el);
			if (!t.startsWith("View Details") || t.includes("Change Business Domain")) continue;
			if (!visible(el)) continue;
			hits.push(el);
		}
		// The item itself is the outermost element that is only the item.
		const outer = hits.filter((el) => !hits.some((other) => other !== el && other.contains(el)));
		if (outer.length === 1) return { item: outer[0] };
		return { reason: outer.length ? "more than one View Details item was showing" : null };
	}

	function closeMenu() {
		document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", keyCode: 27, bubbles: true }));
	}

	/**
	 * Waits for this tab to be the one on screen, asking the extension to bring it
	 * forward. True once it is.
	 */
	async function whenVisible(sendFront) {
		if (!document.hidden) return true;
		doing = "waiting for this tab to be brought to the front";
		sendFront();
		return !!(await waitFor(() => !document.hidden, FRONT_MS));
	}

	/** Opens one vehicle's detail page from its row and reads it. */
	async function readOne(tr, row, deadline) {
		const cells = [...tr.children];
		const actions = cells[cells.length - 1];
		const button = actions && actions.querySelector("button[aria-haspopup], button");
		if (!button) return { reason: "its Actions button was not found" };

		doing = "opening the Actions menu";
		button.click();
		let found = null;
		await waitFor(() => {
			found = viewDetailsItem();
			return found.item || found.reason;
		}, MENU_GRACE_MS);
		if (!found || !found.item) {
			closeMenu();
			return { reason: (found && found.reason) || "its Actions menu showed no View Details item" };
		}
		doing = "waiting for the vehicle's page";
		found.item.click();

		// The route changes first; the permit card, then the right vehicle, follow.
		const want = row._number;
		let detail = null;
		const arrived = await waitFor(() => {
			if (!onDetailPage()) return false;
			detail = readDetail();
			if (!detail) return false;
			const number = (detail.plate.split("-").pop() || "").trim();
			return number === want;
		}, Math.min(DETAIL_GRACE_MS, Math.max(0, deadline - Date.now())));
		doing = "reading the vehicle's page";
		if (!arrived) {
			if (!onDetailPage()) return { reason: "View Details did not open the vehicle's page" };
			return { reason: `the page opened showed ${detail ? `plate ${detail.plate}` : "no permit card"}, not this vehicle` };
		}

		// The number matched; the rest of the plate has to as well.
		const emirate = detail.emirate.trim().toUpperCase();
		const category = detail.category.trim().toUpperCase();
		if ((emirate && emirate !== row._emirate.toUpperCase()) || (category && category !== row._code.toUpperCase())) {
			return { reason: `the page opened was ${detail.emirate} ${detail.category} ${detail.plate}, not this vehicle` };
		}
		return { detail };
	}

	/**
	 * Visits the detail page of every active-permit vehicle in `rows` and returns
	 * the rows with `_permit_number` / `_detail_expiry` filled - or `_detail_note`
	 * saying why not. A vehicle that fails is one vehicle; the pass goes on.
	 */
	async function readPermitNumbers(rows, deadline, progress) {
		const merged = rows.map((row) => ({ ...row }));
		// One vehicle, one detail page - but it can be listed once per business
		// domain, and every one of its rows gets what the page said.
		const byKey = new Map();
		for (const row of merged) {
			if (!ACTIVE_RE.test(row._permit || "")) continue;
			const key = rowKeyOf(row);
			if (!byKey.has(key)) byKey.set(key, []);
			byKey.get(key).push(row);
		}
		const pending = new Set(byKey.keys());
		const total = pending.size;
		let read = 0;
		let filtered = null; // null: not tried yet; false: the tile did not filter
		let stop = null;
		let beat = () => {};
		const heartbeat = setInterval(() => beat(), HEARTBEAT_MS);
		try {

			while (pending.size) {
				if (Date.now() > deadline) { stop = "the read ran out of time"; break; }
				if (!signedIn()) { stop = "the account was signed out"; break; }
				doing = "going back to the vehicle list";
				if (!(await backToList(deadline))) { stop = "the vehicle list did not come back after a detail page"; break; }

				if (filtered !== false) {
					doing = "applying the Active Permits filter";
					const ok = await filterToActive(deadline);
					if (!ok) {
						if (filtered === null) {
							filtered = false; // walk the unfiltered list from here on
							if (!(await backToList(deadline))) { stop = "the vehicle list did not settle"; break; }
						} else {
							stop = "the Active Permits filter stopped working part-way";
							break;
						}
					} else {
						filtered = true;
					}
				}

				doing = "finding the next vehicle in the list";
				const match = await findPending(pending, deadline);
				if (!match) break; // the rest are not in the list as it now stands
				const [tr, listed] = match;
				const key = rowKeyOf(listed);
				const vehicleRows = byKey.get(key);
				pending.delete(key);
				const position = `${total - pending.size} of ${total}`;
				progress({ stage: "reading", message: `Reading permit number ${position}…` });
				doing = "starting";
				beat = () => progress({ stage: "reading", needsFront: document.hidden, message: `Reading permit number ${position} - ${doing}…` });

				banner("Fine Fetch is reading permit numbers - please keep this tab in front until it finishes.");
				if (!(await whenVisible(() => progress({ stage: "reading", needsFront: true, message: `Reading permit number ${position} - keep the Asateel tab in front…` })))) {
					stop = "the Asateel tab was not in front, so its menus cannot open";
					for (const row of vehicleRows) row._detail_note = stop;
					break;
				}

				// One vehicle gets VEHICLE_MS and no more.
				const visitDeadline = Math.min(deadline, Date.now() + VEHICLE_MS);
				const result = await readOne(tr, listed, visitDeadline);
				for (const row of vehicleRows) {
					if (result.detail) {
						row._permit_number = result.detail.permit_number;
						row._detail_expiry = result.detail.expiry;
					} else {
						row._detail_note = result.reason;
					}
				}
				if (result.detail) read += 1;
			}

			for (const key of pending) {
				for (const row of byKey.get(key)) row._detail_note = stop || "it was not found in the list on the way back";
			}
			// Leave the operator on the list, not on the last vehicle visited.
			if (onDetailPage()) await backToList(deadline);

		} finally {
			clearInterval(heartbeat);
			banner(null);
		}

		const missed = total - read;
		return {
			rows: merged,
			coverage: [{
				list: DETAIL_LIST,
				read,
				reason: missed ? `${missed} of ${total} not read${stop ? ` - ${stop}` : ""}` : null,
				window: null,
			}],
		};
	}

	chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
		if (!message || (message.type !== "TFF_READ" && message.type !== "TFF_DETAILS")) return;

		const progress = (payload) => {
			chrome.runtime
				.sendMessage({ type: "TFF_PROGRESS", requestId: message.requestId, ...payload })
				.catch(() => {
					// The desk tab can be closed mid-run. Losing the progress line is
					// not a reason to abandon a read in flight.
				});
		};

		if (message.type === "TFF_DETAILS") {
			(async () => {
				const budget = Number(message.budgetMs) > 0 ? Number(message.budgetMs) : DEFAULT_BUDGET_MS;
				const deadline = Date.now() + Math.max(0, budget - BUDGET_MARGIN_MS);
				if (!lastRows) {
					sendResponse({ ok: false, message: "the vehicle list was not read in this tab first" });
					return;
				}
				const result = await readPermitNumbers(lastRows, deadline, progress);
				sendResponse({ ok: true, ...result });
			})().catch((error) => {
				sendResponse({ ok: false, message: String(error && error.message) });
			});
			return true;
		}

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

			// The permit numbers are a second step, asked for in a second message:
			// it navigates away from the list, and if the page reloads on the way
			// this script goes with it. Sent separately, the vehicles read above
			// are already in the background's hands when that happens.
			lastRows = rows;
			const active = rows.filter((row) => ACTIVE_RE.test(row._permit || "")).length;
			sendResponse({
				ok: true,
				state: "read",
				rows,
				truncated: !!reason,
				coverage: [{ list: LIST, read: rows.length, reason: reason || null, window: null }],
				followUp: active
					? { request: { type: "TFF_DETAILS" }, list: DETAIL_LIST, message: `Reading ${active} permit number(s)…` }
					: null,
			});
		})().catch((error) => {
			sendResponse({ ok: false, state: "error", message: String(error && error.message) });
		});

		// Keeps the message channel open for the async work above.
		return true;
	});
})();
