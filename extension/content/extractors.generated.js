// GENERATED FILE - DO NOT EDIT BY HAND.
// Generated 2026-10-11 from asateel.py, darb.py, rakta.py, rta.py, salik.py, tamm.py
// by extension/tools/generate_extractors.py. Change the constants in those
// Python modules and re-run the generator; edits made here are lost and,
// worse, silently diverge from what the server-side fetcher reads.
//
// Keyed by the `client_reader` each fetcher declares, which is the same name
// the server returns from get_client_fetch_target - so the reader that runs
// is always the one that portal's fetcher named.
//
// Each value is the portal-reading arrow function exactly as the fetcher
// evaluates it, comments and all - so a fix to either side is one
// regeneration away from reaching the other.

globalThis.PORTAL_EXTRACTORS = {

	// from asateel.py
	asateel: {

		// EXTRACT_ROWS_JS
		extractRows: () => {
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
},

		// NEXT_PAGE_JS
		nextPage: () => {
	const pager = document.querySelector('ul.pagination');
	if (!pager) return false;
	const next = pager.querySelector('button[aria-label="Go to next page"]');
	if (!next || next.disabled || next.getAttribute('aria-disabled') === 'true') return false;
	next.click();
	return true;
},
	},

	// from darb.py
	darb: {

		// EXTRACT_ROWS_JS
		extractRows: () => {
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
    return (copy.textContent || '').replace(/\s+/g, ' ').trim();
  };

  // The plate is a component, not a string, and it hands over its three parts
  // already separated - which is what lets the server match a vehicle without
  // parsing anything.
  const plateOf = (td) => {
    const vp = td && td.querySelector('vehicle-plate');
    if (!vp) return { code: '', emirate: '', number: '', text: text(td) };
    const part = (sel) => {
      const el = vp.querySelector(sel);
      return el ? (el.textContent || '').replace(/\s+/g, ' ').trim() : '';
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
      .map((th) => (th.textContent || '').replace(/\s+/g, ' ').trim());

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
        ? (word.textContent || '').replace(/\s+/g, ' ').trim()
        : badge ? (badge.textContent || '').replace(/\s+/g, ' ').trim() : text(cells[c.status]);

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
},
	},

	// from rakta.py
	rakta: {

		// EXTRACT_ROWS_JS
		extractRows: () => {
  const list = document.querySelector('#fines_enquiry .fine_enquiry_list');
  if (!list) return null;

  const table = list.querySelector('table.mytable');
  if (!table) {
    // The portal renders <h4 class="list_heading">No Record Found</h4> in
    // place of the table. That is an answer - zero fines for this plate - and
    // is reported as an empty array, never as a failure to read.
    return list.querySelector('h4') ? [] : null;
  }

  return [...table.querySelectorAll('tbody tr')].map(tr => {
    const cells = [...tr.children].map(td => (td.textContent || '').trim());
    return {
      _fineId:     cells[0] || '',
      _details:    cells[1] || '',
      _amount:     cells[2] || '',
      _issuedDate: cells[3] || '',
      _status:     cells[4] || '',
    };
  }).filter(row => row._fineId);
},
	},

	// from rta.py
	rta: {

		// EXTRACT_ROWS_JS
		extractRows: () => [...document.querySelectorAll('div.finesRowList')].map(list => {
  const row = {};
  const cells = [...list.children];

  // First cell, no label: "MAKE MODEL, YEAR, COLOUR". Kept whole rather than
  // split - the make can itself contain a comma, and nothing downstream needs
  // the pieces.
  if (cells.length) row.vehicle = (cells[0].innerText || '').trim();

  cells.slice(1).forEach(cell => {
    const label = cell.querySelector('span');
    if (!label) return;
    const key = (label.textContent || '').trim().replace(/:$/, '');
    // The value is everything the label is not. Subtracting the label's own
    // text is what keeps "Amount" out of "Amount AED 200".
    const value = (cell.innerText || '').replace(label.textContent || '', '').trim();
    if (key) row[key] = value;
  });

  // RTA's internal row key, on the selection checkbox. Recorded because it is
  // the only identifier present before a detail panel is opened, which makes it
  // the one way to tell "this row was read" from "this row was skipped".
  const tr = list.closest('tr');
  const box = tr && tr.querySelector('input.p-checkbox-input');
  const aria = (box && box.getAttribute('aria-label')) || '';
  const key = aria.match(/\b(C?TCK)_(\d+)\b/);
  if (key) { row._rowKind = key[1]; row._rowId = key[2]; }

  return row;
}).filter(row => Object.keys(row).length > 1),

		// NEXT_PAGE_JS
		nextPage: () => {
  const next = document.querySelector('.p-paginator-next');
  if (!next) return null;
  if (next.disabled || next.classList.contains('p-disabled')) return null;
  next.click();
  return true;
},

		// READ_PANEL_JS
		readPanel: () => {
  const list = document.querySelector('div.dataList');
  if (!list) return null;
  const out = {};

  [...list.children].forEach(cell => {
    if (cell.tagName !== 'DIV') return;
    const label = cell.querySelector('span');
    if (!label) return;
    const key = (label.textContent || '').trim().replace(/:$/, '');
    if (!key) return;
    const value = cell.querySelector('p');
    if (value) { out[key] = (value.textContent || '').trim(); return; }
    // No <p>: the value is the <ul> that follows this div.
    const after = cell.nextElementSibling;
    if (after && after.tagName === 'UL') {
      out[key] = [...after.querySelectorAll('li')]
        .map(li => (li.innerText || '').trim()).filter(Boolean).join('; ');
    }
  });

  // The plate is structured markup, so the code and the number come out as
  // separate values instead of a string that has to be split back apart.
  const info = document.querySelector('div.vInfo');
  if (info) {
    const heading = info.querySelector('h4');
    if (heading) out._vehicle = (heading.textContent || '').trim();
    const plate = info.querySelector('[data-testid="PlateComponent"]');
    if (plate) {
      const code = plate.querySelector('[data-testid="PlateCharacter"]');
      out._code = code ? (code.textContent || '').trim() : null;
      const number = [...plate.children].find(child => child !== code);
      out._number = number ? (number.textContent || '').trim() : null;
    }
  }

  return out;
},
	},

	// from salik.py
	salik: {

		// EXTRACT_ROWS_JS
		extractRows: () => {
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
},
	},

	// from tamm.py
	tamm: {

		// EXTRACT_ROWS_JS
		extractRows: () => [...document.querySelectorAll('tr.ui-lib-table-row')]
  // The header carries the same row class as the data rows and differs only by
  // this flag. Without it the header parses into a fine whose ticket number is
  // the literal text "Fine Number" - which then stages as a real liability.
  .filter(tr => !tr.querySelector('td[data-is-header="true"]'))
  .map(tr => {
  const row = {};
  tr.querySelectorAll('td[data-id]').forEach(td => {
    row[td.getAttribute('data-id')] = (td.innerText || '').trim();
  });
  const plate = tr.querySelector('.ui-lib-number-plate');
  if (plate) {
    const text = sel => {
      const el = plate.querySelector(sel);
      return el ? (el.innerText || '').trim() : null;
    };
    row._code = text('.ui-lib-number-plate__serial-text-item');
    row._emirate = text('.ui-lib-number-plate__serial-area-item-ar');
    row._number = text('.ui-lib-number-plate__register-text');
  }
  return row;
}).filter(row => Object.keys(row).length > 1),

		// NEXT_PAGE_JS
		nextPage: () => {
  const root = document.querySelector('.ui-lib-pagination') || document;
  const leaves = [...root.querySelectorAll('*')].filter(el =>
    el.children.length === 0 && /^\d{1,3}$/.test((el.textContent || '').trim()));

  const isActive = el => {
    for (let n = el; n && n !== root; n = n.parentElement) {
      const cls = (n.getAttribute && (n.getAttribute('class') || '')) || '';
      if (/active|selected|current/i.test(cls)) return true;
      if (n.getAttribute && n.getAttribute('aria-current')) return true;
    }
    return false;
  };

  const numbered = leaves.map(el => ({el, n: parseInt((el.textContent || '').trim(), 10)}));
  const active = numbered.find(x => isActive(x.el));
  if (active) {
    const target = numbered.find(x => x.n === active.n + 1);
    if (target) {
      (target.el.closest('button, a, li') || target.el).click();
      return active.n + 1;
    }
  }

  const next = [...root.querySelectorAll('button, a')].find(b => {
    const label = ((b.getAttribute('aria-label') || '') + ' ' + (b.className || '')).toLowerCase();
    return /next/.test(label) && !b.hasAttribute('disabled');
  });
  if (next) { next.click(); return 'next'; }
  return null;
},

		// READ_PANEL_JS
		readPanel: () => {
  const labels = ['Ticket Number', 'Plate Number', 'Description',
                  'Fine Location', 'Status', 'Ticket Type'];
  const panel = [...document.querySelectorAll('div, section, aside')]
    .filter(el => {
      const t = el.innerText || '';
      return t.includes('Ticket Number') && t.includes('Description');
    })
    .sort((a, b) => (a.innerText || '').length - (b.innerText || '').length)[0];
  if (!panel) return null;
  const lines = (panel.innerText || '').split('\n').map(s => s.trim()).filter(Boolean);
  const out = {};
  for (let i = 0; i < lines.length - 1; i++) {
    if (labels.includes(lines[i]) && !labels.includes(lines[i + 1])) {
      out[lines[i]] = lines[i + 1];
    }
  }
  return out;
},
	},
};

globalThis.PORTAL_ORIGINS = {
 "asateel": "https://asateelplus.itc.gov.ae",
 "darb": "https://darb.qmobility.ae",
 "rakta": "https://smart.rakta.gov.ae",
 "rta": "https://ums.rta.ae",
 "salik": "https://customers.salik.ae",
 "tamm": "https://www.tamm.abudhabi"
};
