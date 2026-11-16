{
    "name": "MAT Product Replacement",
    "version": "18.0.1.1.0",
    "category": "Inventory/Inventory",
    "summary": "Controlled, traceable replacement of outdated products",
    "description": """
Product Replacement
===================
Replace an outdated product by a new one in a single, audited action.

* The replacement is created as an ordinary duplicate of the original.
* Original and replacement are linked in both directions.
* The original becomes "Deprecated", the replacement "New".
* Who, when and why are stored in a read-only audit record.
* Stock and existing documents stay on the original, which is never archived.
* Only users with the "Product Replacement: Manager" access right can run the action.
* A product can be replaced only once.
* Everything happens in one savepoint: a failure leaves no partial changes.

Scope: product templates with exactly one variant.
""",
    "license": "LGPL-3",
    "depends": ["sale_management", "stock"],
    "data": [
        "security/product_replacement_security.xml",
        "security/ir.model.access.csv",
        "data/product_replacement_reason_data.xml",
        "wizard/product_replacement_wizard_views.xml",
        "views/product_replacement_reason_views.xml",
        "views/product_replacement_views.xml",
        "views/product_template_views.xml",
        "views/product_replacement_menus.xml",
    ],
    "demo": [
        "demo/mat_product_replacement_demo.xml",
    ],
    "installable": True,
    "application": False,
}
