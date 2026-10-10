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
// 2. **There is nothing to submit, but there is something to wait for.** Both
//    lists - including the one behind the inactive tab - fetch themselves the
//    moment the page mounts, so the reader never touches the tab strip and
//    never runs a search. But each mounts EMPTY first and fills in when DARB
//    answers, behind its own loader. Reading before then would report no
//    fines, so the reader waits for every loader to clear.
//
// 3. **It refuses rather than reporting zero when signed out.** The login page
//    lives under the same path prefix, so this script runs there too. Saying
//    "no fines" because nobody was signed in is the one failure that would put
//    a clean bill in front of somebody who owes money.
//
// 4. **Past ten fines, a list is paged, and every page is read or the list is
//    reported unread.** DARB's compiled template binds each table's paginator
//    to `totalCount > gridPageSize`, page size 10, and each page is a server
//    round trip. So a list with no paginator is complete, and one with a
//    paginator is walked with its own next control. Anything that does not
//    check out - a page that never loads, a short page before the last, a fine
//    seen on two pages - ends that list as unread rather than read in part
//    and passed off as whole. The walk has been tested against a stand-in
//    built to the template, not yet against a real paged list.
//
// It never signs in, never types a credential and never answers the reCAPTCHA -
// the operator does all three in their own browser. It never clicks Pay Fines,
// the per-row Pay Now buttons, or anything else in a row.

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

	// One page of a paged list is one server request. This is its ceiling.
	const PAGE_GRACE_MS = 45000;

	// Bounds the walk. Five hundred fines on one account is far beyond anything
	// seen; a longer list is reported unread rather than read in part.
	const MAX_PAGES = 50;

	// Kept back from the background's read budget so the answer still has
	// time to reach it when the walk runs to the limit.
	const BUDGET_MARGIN_MS = 10000;
	const DEFAULT_BUDGET_MS = 20 * 60 * 1000;

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

	// DARB's own loading overlay. Each list's component holds an
	// `app-page-loading` that renders this element while that list's search is
	// in flight, and removes it when the answer is in.
	const LOADER = ".loadingAber";
	const FINES_COMPONENTS = "owner-fines, mawaqif-fines";

	/** The component a table belongs to - where its loader and totals live.
	 *
	 * Falls back to the whole document if the component tags ever change, so
	 * the loader check gets broader rather than silently disappearing.
	 */
	const componentOf = (el) => (el && el.closest(FINES_COMPONENTS)) || document;

	/** Whether a list - or, given the document, any list - is still loading. */
	function loadingIn(scope) {
		if (scope !== document) return !!scope.querySelector(LOADER);
		const components = document.querySelectorAll(FINES_COMPONENTS);
		if (!components.length) return !!document.querySelector(LOADER);
		return [...components].some((component) => !!component.querySelector(LOADER));
	}

	/** Both tables, once neither is loading and their contents have stopped changing.
	 *
	 * **Both lists mount EMPTY and fetch afterwards.** DARB's tables are lazy:
	 * each renders its "No Records" placeholder first, raises its loader, and
	 * fills in when the server answers. A table that has merely stopped
	 * changing may be one whose answer has not arrived - and reading it then
	 * reports no fines over a list that has them. So settled means no loader
	 * showing AND nothing changing for SETTLE_MS. A list still loading when
	 * the grace runs out is left to readList, which reports it unread.
	 */
	async function awaitTables() {
		const appeared = await waitFor(
			() => document.querySelector("p-table table thead th"),
			TABLES_GRACE_MS
		);
		if (!appeared) return false;

		const state = () =>
			[...document.querySelectorAll("p-table table")]
				.map((table) => signature(table.closest("p-table") || table))
				.join("\u0000");
		let last = state();
		let steadySince = Date.now();
		const deadline = Date.now() + TABLES_GRACE_MS;

		while (loadingIn(document) || Date.now() - steadySince < SETTLE_MS) {
			if (Date.now() > deadline) break;
			await sleep(POLL_MS);
			const now = state();
			if (now !== last || loadingIn(document)) {
				last = now;
				steadySince = Date.now();
			}
		}
		return true;
	}

	/** The list's own "Total Pending Fines" figure in AED, or null.
	 *
	 * DARB shows this card per list, from a separate request. null whenever
	 * it cannot be read cleanly - no component, no card, its own loader still
	 * showing, or no number - so the check that uses it only ever adds doubt.
	 */
	function pendingTotal(component) {
		if (!component || component === document) return null;
		const card = component.querySelector(".secondaryBg");
		if (!card || card.querySelector(".div_loader")) return null;
		const figure = [...card.querySelectorAll("p.whiteText")].find(
			(p) => !p.classList.contains("fz-12")
		);
		const n = figure ? parseFloat((figure.textContent || "").replace(/,/g, "").trim()) : NaN;
		return Number.isFinite(n) ? n : null;
	}

	// A table is identified by how many columns its header row has, which is
	// the one thing about it that survives the language toggle. Both counts are
	// DARB's compiled templates: twelve for Traffic Toll, ten for Mawaqif.
	const LIST_BY_HEADER_COUNT = { 12: "Traffic Toll", 10: "Mawaqif" };

	/** Rows in one table that are meant to carry a fine.
	 *
	 * The empty-list placeholder is a single cell spanning the table, so
	 * anything wider is a fine - whether or not the extractor could read it.
	 * Counting independently of the extractor is the point: a row shape the
	 * extractor does not know is skipped there, and only this count notices.
	 */
	const fineRows = (host) =>
		[...host.querySelectorAll("tbody tr")].filter((tr) => tr.children.length > 1);

	/** What one table shows right now, compact enough to compare across pages. */
	const signature = (host) =>
		fineRows(host)
			.map((tr) => (tr.textContent || "").replace(/\s+/g, " ").trim())
			.join("\n");

	/** The table's own next control. PrimeNG renders it only when it pages. */
	const nextControl = (host) => host.querySelector("a.ui-paginator-next");

	/** PrimeNG binds `ui-state-disabled` on next to its isLastPage(). */
	const onLastPage = (link) => link.classList.contains("ui-state-disabled");

	/** The page number the pager has marked active, or null. */
	function activePage(host) {
		const link = host.querySelector("a.ui-paginator-page.ui-state-active");
		const n = link ? parseInt((link.textContent || "").trim(), 10) : NaN;
		return Number.isFinite(n) ? n : null;
	}

	/** The rows-per-page the pager's own dropdown shows, or null if not found.
	 *
	 * A cross-check only: the operator can change it, which is why the page
	 * size is taken from page one rather than assumed to be ten.
	 */
	function rowsPerPageShown(host) {
		const label = host.querySelector(".ui-paginator .ui-dropdown-label");
		const n = label ? parseInt((label.textContent || "").trim(), 10) : NaN;
		return Number.isFinite(n) ? n : null;
	}

	/** Wait until a list has stopped loading and its table has stood still for SETTLE_MS. */
	async function settle(host, deadline) {
		const component = componentOf(host);
		let last = signature(host);
		let steadySince = Date.now();
		while (loadingIn(component) || Date.now() - steadySince < SETTLE_MS) {
			if (Date.now() > deadline) return false;
			await sleep(POLL_MS);
			const now = signature(host);
			if (now !== last || loadingIn(component)) {
				last = now;
				steadySince = Date.now();
			}
		}
		return true;
	}

	/** Every fine in one list, and the coverage line that says how it went.
	 *
	 * Page one is checked exactly as before: the rows on the page are counted
	 * independently of the extractor, and any shortfall is `read: null` -
	 * unread, which forces `truncated` and downgrades the run instead of
	 * quietly blessing it. That guard predates the pager and still matters: a
	 * row shape the extractor does not know would otherwise land as a list
	 * reporting no fines.
	 *
	 * With no pager, that is the whole list. With one, the walk clicks the
	 * table's own next control and waits for that table to change, page after
	 * page, until next is disabled. Rows read before a failure are still
	 * returned - they are real fines - but the list is marked unread, so the
	 * run says it is incomplete.
	 */
	async function readList(host, list, deadline, progress) {
		const rowsOfList = () => (extractRows() || []).filter((row) => row._list === list);
		const unread = (rows, reason) => ({ rows, entry: { list, read: null, reason } });
		const component = componentOf(host);

		/** The list as read - unless DARB's own total says it cannot be.
		 *
		 * A search that fails on DARB's side clears the loader and leaves the
		 * empty placeholder, which is indistinguishable from "no fines" in the
		 * table itself. The pending-total card is a separate request, so a
		 * balance there with no unpaid fine read means the table is not the
		 * whole story. It can also mean DARB counts fines it does not list
		 * here; either way the run must not say this list was read clean.
		 */
		const finished = (rows) => {
			const pending = pendingTotal(component);
			if (pending !== null && pending > 0 && !rows.some((row) => row._paid === false)) {
				return unread(
					rows,
					`DARB shows AED ${pending} pending on this list, but no unpaid fine could be read`
				);
			}
			return { rows, entry: { list, read: rows.length } };
		};

		if (loadingIn(component)) return unread([], "it was still loading when the wait ran out");

		const first = rowsOfList();
		const rendered = fineRows(host).length;
		if (rendered !== first.length) {
			return unread(
				first,
				`${rendered} row(s) are on the page in a shape this build does not ` +
					`recognise, and ${first.length} could be read`
			);
		}
		for (const row of first) row._page = 1;

		if (!nextControl(host)) return finished(first);

		// Paged. DARB only shows a pager when the list is longer than one page,
		// so page one is full and its size is the page size.
		const pageSize = first.length;
		const shown = rowsPerPageShown(host);
		if (shown !== null && shown !== pageSize) {
			return unread(
				first,
				`its first page held ${pageSize} fine(s) while the pager is set to ${shown} a page`
			);
		}

		const all = [...first];
		const seen = new Set(first.map((row) => row._ticket).filter(Boolean));
		let lastCount = pageSize;

		for (let page = 2; ; page++) {
			const link = nextControl(host);
			if (!link) return unread(all, `its pager disappeared after page ${page - 1}`);
			if (onLastPage(link)) break;

			// More pages follow, so the one just read had to be full.
			if (lastCount !== pageSize) {
				return unread(
					all,
					`page ${page - 1} held ${lastCount} fine(s) where ${pageSize} were ` +
						`expected, with more pages after it`
				);
			}
			if (page > MAX_PAGES) return unread(all, `it runs past ${MAX_PAGES} pages`);
			if (Date.now() > deadline) return unread(all, `time ran out before page ${page}`);

			progress({ stage: "reading", message: `Reading ${list}, page ${page}…` });

			const before = signature(host);
			link.click();
			const loaded = await waitFor(
				() => signature(host) !== before && fineRows(host).length > 0,
				Math.max(0, Math.min(PAGE_GRACE_MS, deadline - Date.now()))
			);
			if (!loaded) return unread(all, `page ${page} did not load`);
			if (!(await settle(host, deadline))) return unread(all, `time ran out on page ${page}`);
			if (activePage(host) !== page) {
				return unread(all, `the pager did not move to page ${page}`);
			}

			const rows = rowsOfList();
			const onPage = fineRows(host).length;
			if (onPage !== rows.length) {
				return unread(
					all,
					`page ${page} has ${onPage} row(s) on the page and ${rows.length} could be read`
				);
			}
			for (const row of rows) {
				// The list moved under the walk - a fine paid or added mid-read
				// shifts every later page by one. Any count from here is wrong.
				if (row._ticket && seen.has(row._ticket)) {
					return unread(all, `the list changed while it was being read (page ${page})`);
				}
				if (row._ticket) seen.add(row._ticket);
				row._page = page;
				all.push(row);
			}
			lastCount = rows.length;
		}

		return finished(all);
	}

	/** Every fines table on the page, read list by list. */
	async function readAllLists(deadline, progress) {
		const rows = [];
		const coverage = [];

		for (const table of document.querySelectorAll("p-table table")) {
			const host = table.closest("p-table") || table;
			const headerCount = table.querySelectorAll("thead th").length;
			const list = LIST_BY_HEADER_COUNT[headerCount];

			if (!list) {
				const rendered = fineRows(host).length;
				coverage.push(
					rendered
						? {
								list: `unrecognised (${headerCount} columns)`,
								read: null,
								reason: `${rendered} row(s) are on the page in a shape this build does not recognise, and 0 could be read`,
							}
						: { list: `unrecognised (${headerCount} columns)`, read: 0 }
				);
				continue;
			}

			const result = await readList(host, list, deadline, progress);
			rows.push(...result.rows);
			coverage.push(result.entry);
		}
		return { rows, coverage };
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
			const budget = Number(message.budgetMs) > 0 ? Number(message.budgetMs) : DEFAULT_BUDGET_MS;
			const deadline = Date.now() + Math.max(0, budget - BUDGET_MARGIN_MS);

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

			if (extractRows() === null) {
				sendResponse({ ok: false, state: "no-table" });
				return;
			}

			const { rows, coverage } = await readAllLists(deadline, progress);

			// Checked again after the walk, which can take a while: a session
			// that ended part-way leaves later pages unread behind a pager that
			// looked finished.
			if (!signedIn()) {
				sendResponse({ ok: false, state: "not-signed-in" });
				return;
			}

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
