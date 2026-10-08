import frappe

DOCTYPE = "Toll Tariff"


def toll(band, days, frm, to, amount, per="Transaction", notes=None):
	return dict(kind="Toll", band=band, days=days, from_time=frm, to_time=to, amount=amount, per=per, notes=notes)


def penalty(band, amount, per, notes=None):
	return dict(kind="Penalty", band=band, days="All", amount=amount, per=per, notes=notes)


TARIFFS = [
	{
		"authority": "Darb",
		# The page states no effective date; this is the date it was read.
		"effective_from": "2026-10-08",
		"verified_on": "2026-10-08",
		"source_url": "https://admobility.gov.ae/en/darb-fees",
		# vat_applies deliberately unset: the page does not say.
		"notes": (
			"Fees: https://admobility.gov.ae/en/darb-fees  Fines: https://admobility.gov.ae/en/darb-fines. "
			"No daily or monthly cap on tolls. Tolls do not apply on Sundays or official holidays. "
			"effective_from is the date the page was read, not a published start date."
		),
		"rates": [
			toll("Peak AM", "Mon-Sat", "07:00:00", "09:00:00", 4, notes="Except official holidays"),
			toll("Peak PM", "Mon-Sat", "15:00:00", "19:00:00", 4, notes="Except official holidays"),
			penalty("Unregistered vehicle - 1st offence", 100, "Offence"),
			penalty("Unregistered vehicle - 2nd offence", 200, "Offence"),
			penalty("Unregistered vehicle - 3rd+ offence", 400, "Offence"),
			penalty("Insufficient balance", 50, "Transaction", "Vehicle registered outside Abu Dhabi"),
			penalty("Plate manipulation", 10000, "Offence"),
			penalty("Damaging gate or machine", 10000, "Offence"),
			penalty("Cap per owner", 10000, "Year cap"),
			penalty("Cap per vehicle", 25000, "Year cap"),
		],
	},
	{
		"authority": "Salik",
		"effective_from": "2026-06-01",
		"verified_on": "2026-10-08",
		"source_url": "https://www.salik.ae/en/Toll-Gates/variable-toll-rates",
		"vat_applies": 1,
		"vat_rate": 5,
		"notes": (
			"VAT applies from 2026-06-01. Sunday 16:00-20:00 and 20:00-01:00 bands are not seeded "
			"(not confirmed). Ramadan hours differ and are not seeded. Penalty amounts unknown - "
			"the source page is geo-blocked outside the UAE."
		),
		"rates": [
			toll("Peak", "Mon-Sat", "06:00:00", "10:00:00", 6),
			toll("Low-Peak", "Mon-Sat", "10:00:00", "16:00:00", 4),
			toll("Peak", "Mon-Sat", "16:00:00", "20:00:00", 6),
			toll("Low-Peak", "Mon-Sat", "20:00:00", "01:00:00", 4, notes="Runs past midnight"),
			toll("Off-Peak", "Mon-Sat", "01:00:00", "06:00:00", 0),
			toll("Peak", "Sunday", "06:00:00", "10:00:00", 4),
			toll("Low-Peak", "Sunday", "10:00:00", "16:00:00", 4),
		],
	},
]


def execute():
	"""Seed the verified public tariffs, creating only what is missing.

	Create-only so a person's later correction to a tariff is never overwritten
	by a deploy; a changed tariff is a new document with a new effective_from.
	Public rates only - nothing here comes from a client. Transport Project
	Shift salik_rate / darb_rate are deliberately NOT written.
	"""
	frappe.flags.in_patch = True
	for t in TARIFFS:
		if frappe.db.exists(DOCTYPE, {"authority": t["authority"], "effective_from": t["effective_from"]}):
			continue
		frappe.get_doc({"doctype": DOCTYPE, **t}).insert(ignore_permissions=True)
