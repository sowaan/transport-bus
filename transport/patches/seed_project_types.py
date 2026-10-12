import frappe

# The client's project sheet types a contract as Monthly, Weekly or Daily. Created
# if missing, never edited: Project Type is core ERPNext data and a site may have
# its own descriptions on records of the same name.
PROJECT_TYPES = ("Monthly", "Weekly", "Daily")


def execute():
	for name in PROJECT_TYPES:
		if not frappe.db.exists("Project Type", name):
			frappe.get_doc({"doctype": "Project Type", "project_type": name}).insert(ignore_permissions=True)
