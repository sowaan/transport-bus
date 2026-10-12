# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

"""The pump price of a fuel from a date - one record a month.

The UAE announces fuel prices monthly. A Rate Calculation costs fuel at the latest
price on or before its date, so quotes made in March use March's price whatever
happens in April."""

from frappe.model.document import Document


class TransportFuelPrice(Document):
	pass
