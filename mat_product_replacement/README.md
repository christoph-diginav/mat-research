# MAT Product Replacement (Odoo 18)

Technical name: `mat_product_replacement`

Controlled, traceable replacement of an outdated product by a new one.

Scope: product templates with exactly one variant.

## What it does

On a product form, an authorised user clicks **Replace**, chooses a reason, optionally adds an explanation, and confirms. In one transaction the module then:

1. creates the replacement as an ordinary duplicate of the original;
2. writes an audit record (original, replacement, user, date, reason, explanation);
3. sets a sales warning on the original ("deprecated, replaced by ...");
4. posts a note in the chatter of both products.

The links (**Replaced By** / **Replaces**) and the status (**Deprecated** / **New**) are computed from the audit record, so they cannot drift apart or be edited by hand.

| Requirement | How it is met |
|---|---|
| Link in both directions | `replaced_by_id` and `replaces_id`, computed from the audit record |
| "Deprecated" / "New" | `replacement_state`, computed from the audit record |
| Who, when, why | `product.replacement` (user, date, reason, frozen reason name, explanation) |
| Stock and transactions stay on the original | Nothing is moved; the replacement is a fresh copy |
| Authorised users only | Access right "Product Replacement: Manager", checked server-side |
| No repeated replacement | Guard in Python and a unique constraint in the database |
| Original stays unarchived | `active` is never written |
| Ordinary duplication unchanged | `copy()` is not overridden; replacement fields are not copied |
| No partial changes on failure | All steps run inside one savepoint |

## Dependencies

Standard Odoo only: `sale_management` and `stock`. No third-party module.

## Install

Put the `mat_product_replacement` folder at the root of the Odoo.sh repository (or in any addons path), update the apps list, and install **MAT Product Replacement**.

Setup after install:

- Give users the access right **Product Replacement: Manager** on their user form (Settings > Users, tab Access Rights, section Inventory). The administrator has it automatically.
- To see the warning on sales orders, enable **Sale Warnings** in Sales > Configuration > Settings.
- Reasons are maintained in Sales > Products > Product Replacement Reasons.
- The audit list is in Sales > Products > Product Replacements.

## Demo data

Loaded only on databases created with demo data (the default for an Odoo.sh development branch):

- three lab products with stock on hand: `LAB-BUF-700` (25), `LAB-ETH-096` (12), `LAB-TIP-200` (40);
- one confirmed sales order for 4 x `LAB-BUF-700` (customer reference `LAB-PO-0042`);
- user `lab.manager` (password `lab.manager`), authorised to replace products;
- user `lab.sales` (password `lab.sales`), not authorised.

No replacement is preloaded: it is meant to be done live.

## Tests

```
odoo-bin -d <database> -i mat_product_replacement --test-tags /mat_product_replacement --stop-after-init
```

On Odoo.sh the tests run automatically on a development branch build.

## Known limits (V1)

- The replacement is always a new copy; an existing product cannot be chosen.
- An existing sales warning on the original is overwritten, not merged.
- The sales warning only appears when the product is picked in the order form.
- "New" has no expiry; it lasts until that product is itself replaced.
- A replacement cannot be undone.
- Deprecated products are flagged, not blocked from sales or purchases.
- Users with the replacement access right need access to the Sales app to reach the two menus.
