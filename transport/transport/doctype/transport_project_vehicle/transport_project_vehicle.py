# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

"""One vehicle (and the driver normally allocated to it) on a transport Project.

The client asked for "Project Vehicle / Driver" on the Project and for "vehicle
allocation to driver at the time of a new trip". This is that allocation: when a
Trip picks a vehicle, Trip.default_driver_for_vehicle() looks here first, then at
the vehicle's own `assigned_driver`."""

from frappe.model.document import Document


class TransportProjectVehicle(Document):
	pass
