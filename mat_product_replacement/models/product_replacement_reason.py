from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class ProductReplacementReason(models.Model):
    _name = "product.replacement.reason"
    _description = "Product Replacement Reason"
    _order = "name, id"

    name = fields.Char(required=True)
    active = fields.Boolean(
        default=True,
        help="Archive a reason to hide it from the replacement wizard "
        "while keeping it on past replacements.",
    )

    @api.constrains("name")
    def _check_name_unique(self):
        """Reject duplicates regardless of case, spacing or archived state.

        The list is meant to stay a short, countable set of categories, so
        "Supplier change" and "supplier change " must not coexist.
        """
        all_reasons = self.with_context(active_test=False).search([])
        for reason in self:
            key = (reason.name or "").strip().casefold()
            if not key:
                raise ValidationError(_("A replacement reason needs a name."))
            duplicates = all_reasons.filtered(
                lambda other: other.id != reason.id
                and (other.name or "").strip().casefold() == key
            )
            if duplicates:
                raise ValidationError(
                    _(
                        "The replacement reason \"%(name)s\" already exists"
                        " (possibly archived).",
                        name=duplicates[0].name,
                    )
                )

    @api.ondelete(at_uninstall=False)
    def _unlink_except_used(self):
        used = (
            self.env["product.replacement"]
            .sudo()
            .search_count([("reason_id", "in", self.ids)], limit=1)
        )
        if used:
            raise UserError(
                _(
                    "A reason that was used for a product replacement cannot"
                    " be deleted. Archive it instead."
                )
            )
