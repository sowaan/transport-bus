# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

"""Standing costs for one kind of vehicle, entered once.

The client's UAT note: instead of typing vehicle rent, fuel cost and driver salary
into every Rate Calculation, keep them as master data - and when the vehicle
category, kilometres and seating are chosen, the costs fill in and the proposed
price follows from the margin asked for. A Rate Calculation row looks its figures up
here by category, seating capacity and ownership (company-owned or an outside
supplier's), and the estimator can still edit whatever it fills in.

The name is built from the three, so there can be only one master per combination."""

from frappe.model.document import Document


class TransportCostMaster(Document):
	pass
