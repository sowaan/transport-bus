import frappe

DOCTYPE = "Traffic Fine Portal"

# The host moved with the ITC -> Q Mobility rebrand, verified 2026-09-20: the
# old host redirects to the new one and the /RucWeb path is unchanged.
OLD_HOST = "darb.itc.gov.ae"
NEW_URL = "https://darb.qmobility.ae/RucWeb/login"


def execute():
	"""Point DARB at its current host and key it to its fetcher.

	**Deliberately surgical.** `seed_traffic_fine_portals` is create-only
	precisely so that a deployment cannot overwrite what a person recorded
	against a portal, and its docstring says a later reference change must be
	a patch touching specific fields rather than a blanket overwrite. This is
	that patch, and it touches exactly two.

	What it does NOT touch, and why:

	* `captcha_type` and `authentication`. On a site that has had DARB
	  captured, these hold a finding written by whoever ran the capture - the
	  2026-08-22 note about the bot-management layer is one such. That is worth
	  more than anything shipped here, and today's measurement is recorded in
	  `portals/darb.py` where it cannot overwrite it. New sites get the fuller
	  wording from the seed file instead.
	* `is_enabled` and `has_written_authorization`. Granted per site by a
	  person, never by a deployment.

	`fetcher_key` is the one that changes behaviour. Without it the registry
	lookup falls through to the Side Registry route, which has no fetcher, and
	the operator is told the portal is unrecognised. With it they get
	DarbFetcher's actual reason: the fines are behind a sign-in carrying its
	own reCAPTCHA, behind a bot-management layer, and nobody has captured the
	signed-in table yet.
	"""
	if not frappe.db.exists("DocType", DOCTYPE):
		return

	portals = frappe.get_all(
		DOCTYPE,
		filters={"authority": ["like", "%DARB%"]},
		fields=["name", "public_form_url", "fetcher_key"],
	)

	for portal in portals:
		updates = {}

		# Only rewrite a URL still on the old host. A site that has already
		# been corrected by hand is left exactly as it is.
		if OLD_HOST in (portal.public_form_url or ""):
			updates["public_form_url"] = NEW_URL

		# Only fill an empty key. A site that has pointed this portal at some
		# other fetcher did so on purpose.
		if not (portal.fetcher_key or "").strip():
			updates["fetcher_key"] = "darb"

		if updates:
			frappe.db.set_value(DOCTYPE, portal.name, updates, update_modified=False)
			print(f"DARB: updated {', '.join(sorted(updates))} on {portal.name}")
