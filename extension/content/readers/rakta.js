// Runs inside the RAKTA tab. Reads the fines the portal reports for each of
// the fleet's plates.
//
// What makes this reader unlike the other two, and none of it is a choice:
//
// 1. **It searches once per vehicle.** RAKTA's fines API takes
//    {PlateEmirate, PlateCode, PlateNumber} and has no fleet variant, so a run
//    is a loop over the plates the server sent in `prefill`. TAMM and RTA each
//    get the whole fleet from one search; here the fleet IS the loop.
//
// 2. **It stamps the plate onto every row.** The results table has no plate
//    column - the plate is the question, not part of the answer - so a row
//    left as scraped cannot be matched to a vehicle and would stage unlinked.
//    Each row carries the plate that was just submitted for it.
//
// 3. **It waits on the network, not on the DOM.** See `awaitResponse` below;
//    this is the subtle one and getting it wrong silently attributes one
//    vehicle's fines to another.
//
// It never signs in, because there is nothing to sign into: the Fines Enquiry
// tab is public. It never touches `button.play_btn` ("Pay"), which is wired to
// navigateToPaymentPage.

(() => {
	if (globalThis.__tffRaktaLoaded) return;
	globalThis.__tffRaktaLoaded = true;

	const { extractRows } = globalThis.PORTAL_EXTRACTORS.rakta;

	const POLL_MS = 250;

	// One search is a real round trip. Measured at about two seconds on a good
	// connection; this is the ceiling before a plate is given up on, and it is
	// generous because giving up costs a vehicle's whole fine list.
	const SEARCH_GRACE_MS = 30000;

	// The Angular app is bootstrapped after document-complete and the enquiry
	// form does not exist until it is. Same lesson as RTA: a fixed sleep here
	// reports "the portal has changed" when the only thing wrong is that it had
	// not finished drawing.
	const FORM_GRACE_MS = 60000;

	// After the response lands Angular still has to render it. This is a
	// render wait, not a network wait, which is why it is short.
	const RENDER_SETTLE_MS = 400;

	// Choosing an emirate rewrites the plate-code list. It is a local filter
	// with no request behind it, so this only has to outlast a change
	// detection pass.
	const CODES_GRACE_MS = 5000;

	// The resource-timing buffer is 250 entries by default and a long fleet
	// sweep would overflow it, which would make the response counter go
	// backwards. Raised once, here, rather than cleared between searches -
	// clearing races with an entry that has not been recorded yet.
	const TIMING_BUFFER = 5000;

	const FINE_API = /\/api\/EnquiryManager\/FineEnquiry$/;

	// The portal remembers the last fines search here and replays it on the
	// next page load. Measured: a reload fired a FineEnquiry request at 534ms
	// with nobody having touched the form.
	//
	// That matters twice over. A replay in flight while the first plate is
	// submitted would land first and satisfy the response gate, handing the
	// previous search's rows to this vehicle. And left behind after a run it
	// means the fleet's last plate sits in the browser's session storage for
	// whatever opens the portal next. Cleared on the way in and on the way out.
	const SEARCH_MEMORY_KEY = "fineEnquirySearchParameters";

	// How long the response count has to stand still before the page counts as
	// idle. Covers the replay above; a search itself answers in one to three
	// seconds, so this does not mask a real one.
	const QUIET_MS = 1500;

	const TAB_LINK = 'a[href="#fines_enquiry"]';
	const PANE = "#fines_enquiry";
	const RESULTS = "#fines_enquiry .fine_enquiry_list";

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

	const control = (name) => document.querySelector(`${PANE} [formcontrolname="${name}"]`);

	/** How many fines searches the page has completed.
	 *
	 * **This is the gate the whole reader turns on.** The obvious approach -
	 * click search, wait, read the table - is wrong here, and quietly so.
	 * `fineSubmitForm()` never clears the previous result before calling the
	 * API; it sets `isShowFineDiv` only inside `.then()`. So plate A's table
	 * stays on screen for the whole of plate B's request, and a reader that
	 * polled the DOM would read A's fines and file them under B.
	 *
	 * Watching for the table to *change* does not fix it either: two plates can
	 * legitimately return identical-looking results, and both returning "No
	 * Record Found" is the common case in a clean fleet.
	 *
	 * The portal's XHR shows up in resource timing, which the content script
	 * shares with the page, so counting completed FineEnquiry requests gives an
	 * unambiguous "the answer to MY question has arrived" - no page-context
	 * injection and no guessing.
	 */
	const responseCount = () =>
		performance.getEntriesByType("resource").filter((e) => FINE_API.test(e.name)).length;

	async function awaitResponse(before) {
		const landed = await waitFor(() => responseCount() > before, SEARCH_GRACE_MS);
		if (!landed) return false;
		// The count moves when the response arrives; Angular renders on the
		// next tick or two.
		await sleep(RENDER_SETTLE_MS);
		return true;
	}

	/** Set an Angular reactive-form control so the form model actually updates.
	 *
	 * Same trap as React, different framework: assigning .value moves the DOM
	 * and leaves the FormControl holding its old value, so the form stays
	 * `invalid` and `fineSubmitForm()` returns early without searching. Angular
	 * binds selects on `change` and text inputs on `input`; both are fired, and
	 * the input goes through the prototype's native setter for the same reason
	 * it does in rta.js.
	 */
	function setControlValue(el, value) {
		if (el.tagName === "SELECT") {
			el.value = value;
			el.dispatchEvent(new Event("change", { bubbles: true }));
			return el.value === value;
		}
		const setter = Object.getOwnPropertyDescriptor(
			window.HTMLInputElement.prototype,
			"value"
		).set;
		setter.call(el, value);
		el.dispatchEvent(new Event("input", { bubbles: true }));
		el.dispatchEvent(new Event("change", { bubbles: true }));
		return el.value === value;
	}

	/** The option whose value matches, compared loosely but assigned exactly.
	 *
	 * RAKTA's plate-code lists contain values with trailing spaces - "I " in
	 * Dubai, Umm Al Quwain and Fujairah. Matching on a trimmed comparison and
	 * then assigning `option.value` verbatim is what makes those selectable;
	 * assigning the trimmed text silently fails and leaves the form invalid.
	 */
	function optionValueFor(select, wanted) {
		const target = String(wanted || "").trim().toUpperCase();
		const match = [...select.options].find(
			(o) => String(o.value || "").trim().toUpperCase() === target
		);
		return match ? match.value : null;
	}

	/** Forget the portal's memory of the last fines search. */
	function forgetLastSearch() {
		try {
			sessionStorage.removeItem(SEARCH_MEMORY_KEY);
		} catch {
			// Storage can be blocked. `settleNetwork` below still covers the
			// replay; this only stops it being started in the first place.
		}
	}

	/** Wait until no fines request has completed for QUIET_MS.
	 *
	 * Runs once, before the first plate. Without it the auto-replay described
	 * at SEARCH_MEMORY_KEY can still be in flight when plate one is submitted,
	 * and the response gate would fire on the replay rather than on the answer
	 * to the question just asked.
	 */
	async function settleNetwork() {
		let last = responseCount();
		let quietSince = Date.now();
		while (Date.now() - quietSince < QUIET_MS) {
			await sleep(POLL_MS);
			const now = responseCount();
			if (now !== last) {
				last = now;
				quietSince = Date.now();
			}
		}
	}

	async function awaitForm() {
		return waitFor(() => {
			const emirate = control("fineEmiratesType");
			return emirate && emirate.options.length > 1 ? emirate : null;
		}, FORM_GRACE_MS);
	}

	/** Put the page on the Fines Enquiry tab. Idempotent. */
	function openFinesTab() {
		const link = document.querySelector(TAB_LINK);
		if (!link) return false;
		const pane = document.querySelector(PANE);
		if (!pane || !pane.classList.contains("active")) link.click();
		return true;
	}

	/** Run one plate and return its rows, or why it could not be run.
	 *
	 * Returns `{ rows }` on success - including `rows: []`, which is a real
	 * answer and means this vehicle owes nothing. Anything else is a reason,
	 * and the caller records it rather than letting it read as a clean zero.
	 */
	async function searchPlate(plate) {
		const emirate = control("fineEmiratesType");
		const code = control("finePlateCode");
		const number = control("finePlateNumber");
		if (!emirate || !code || !number) return { reason: "the search form was not on the page" };

		const emirateValue = optionValueFor(emirate, plate.emirate);
		if (!emirateValue) return { reason: `the portal does not offer emirate ${plate.emirate}` };
		setControlValue(emirate, emirateValue);

		// Choosing an emirate rebuilds the code list, and until it has this
		// plate's code cannot be selected.
		//
		// The empty-value test is what makes this safe between plates. The
		// portal's own change handler runs `finePlateCode.setValue("")` before
		// it rebuilds the list, so an empty value is proof the rebuild has
		// happened. Without it, a plate whose code also exists in the PREVIOUS
		// emirate's list would match against that stale list and be selected
		// before the new one arrived.
		const codeValue = await waitFor(
			() => (code.value === "" ? optionValueFor(code, plate.code) : null),
			CODES_GRACE_MS
		);
		if (!codeValue) return { reason: `plate code ${plate.code} is not offered for ${plate.emirate}` };
		setControlValue(code, codeValue);

		if (!setControlValue(number, String(plate.number))) {
			return { reason: "the plate number would not go into the form" };
		}

		const search = document.querySelector(`${PANE} .search_field`);
		if (!search) return { reason: "the search button was not on the page" };

		const before = responseCount();
		search.click();
		if (!(await awaitResponse(before))) {
			return { reason: "the portal did not answer within the time allowed" };
		}

		// null means neither a table nor the no-records heading is there, so
		// the markup is not what this build expects. Deliberately NOT folded
		// into "no fines": an unreadable page and a clean vehicle must never
		// arrive as the same answer.
		const rows = extractRows();
		if (rows === null) return { reason: "the results area was not in the expected shape" };

		return { rows };
	}

	/** Every plate the server sent, in order, within the budget.
	 *
	 * `coverage` holds only plates this reader ATTEMPTED and could not read.
	 * That restraint is load-bearing: background.js turns any entry with
	 * `read === null` into `truncated`, and the server turns `truncated` into
	 * "Completed with Errors". Anything listed here that was never actually
	 * tried would degrade every run forever and drown out a real partial read.
	 */
	async function collectFleet({ plates, budgetMs, progress }) {
		const deadline = budgetMs ? Date.now() + budgetMs : 0;
		const rows = [];
		const coverage = [];
		let truncated = false;

		for (let i = 0; i < plates.length; i++) {
			const plate = plates[i];
			const label = `${plate.emirate} ${plate.code} ${plate.number}`;

			if (deadline && Date.now() > deadline) {
				// Out of time with plates still unasked. Each one is named:
				// the count of what was read cannot distinguish "these
				// vehicles are clean" from "these vehicles were never asked
				// about", and only one of those is safe to act on.
				truncated = true;
				for (let j = i; j < plates.length; j++) {
					const rest = plates[j];
					coverage.push({
						list: `${rest.emirate} ${rest.code} ${rest.number}`,
						read: null,
						reason: "the time budget ran out before this plate",
					});
				}
				break;
			}

			progress({
				stage: "reading",
				message: `Checking ${i + 1} of ${plates.length}: ${label}…`,
				count: rows.length,
			});

			const result = await searchPlate(plate);
			if (result.reason) {
				coverage.push({ list: label, read: null, reason: result.reason });
				continue;
			}

			for (const row of result.rows) {
				// The plate the question was asked with, not anything read off
				// the row. This is what lets the server match a vehicle.
				row._plateEmirate = plate.emirate;
				row._plateCode = plate.code;
				row._plateNumber = plate.number;
				rows.push(row);
			}
			coverage.push({ list: label, read: result.rows.length });
		}

		return { rows, coverage, truncated };
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
			const plates = (message.prefill && message.prefill.plates) || [];
			if (!plates.length) {
				// This portal has no fleet-wide query, so with no plates there
				// is no question to ask. Reported as a refusal, never as zero.
				sendResponse({ ok: false, state: "no-prefill" });
				return;
			}

			try {
				performance.setResourceTimingBufferSize(TIMING_BUFFER);
			} catch {
				// Not fatal. An overflowing buffer makes a search look like it
				// never answered, which reads as a timeout on that plate and is
				// recorded against it rather than passed off as a clean result.
			}

			progress({ stage: "reading", message: "Opening the fines enquiry…" });

			forgetLastSearch();

			if (!openFinesTab() || !(await awaitForm())) {
				sendResponse({ ok: false, state: "no-form" });
				return;
			}

			await settleNetwork();

			let result;
			try {
				result = await collectFleet({
					plates,
					budgetMs: message.budgetMs || 0,
					progress,
				});
			} finally {
				// Whatever happened, the fleet's last plate does not stay in
				// this browser's session storage.
				forgetLastSearch();
			}

			// Not one plate could be asked. That is a broken read, not a fleet
			// with no fines, and it is reported as one.
			if (!result.coverage.some((c) => c.read !== null)) {
				sendResponse({ ok: false, state: "no-table", coverage: result.coverage });
				return;
			}

			sendResponse({
				ok: true,
				state: "read",
				rows: result.rows,
				truncated: result.truncated,
				coverage: result.coverage,
			});
		})().catch((error) => {
			sendResponse({ ok: false, state: "error", message: String(error && error.message) });
		});

		// Keeps the message channel open for the async work above.
		return true;
	});
})();
