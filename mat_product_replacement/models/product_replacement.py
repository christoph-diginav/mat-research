from odoo import api, fields, models


class ProductReplacement(models.Model):
    """Audit record of one product replacement.

    This record is the single source of truth: the links and the status shown
    on the products are computed from it. Nobody has create, write or unlink
    rights on it (see ir.model.access.csv); it is only written by
    ``product.template.replace_product`` after the authorisation check.
    """

    _name = "product.replacement"
    _description = "Product Replacement"
    _order = "date desc, id desc"

    original_tmpl_id = fields.Many2one(
        "product.template",
        string="Original Product",
        required=True,
        index=True,
        ondelete="restrict",
    )
    replacement_tmpl_id = fields.Many2one(
        "product.template",
        string="Replacement Product",
        required=True,
        index=True,
        ondelete="restrict",
    )
    user_id = fields.Many2one(
        "res.users",
        string="Replaced By",
        required=True,
        default=lambda self: self.env.user,
        ondelete="restrict",
    )
    date = fields.Datetime(
        string="Replaced On",
        required=True,
        default=fields.Datetime.now,
    )
    reason_id = fields.Many2one(
        "product.replacement.reason",
        string="Reason",
        required=True,
        ondelete="restrict",
    )
    reason_name = fields.Char(
        string="Reason (as recorded)",
        required=True,
        help="Name of the reason at the time of the replacement. Renaming "
        "the reason later does not change this value.",
    )
    note = fields.Text(string="Explanation")

    _sql_constraints = [
        (
            "original_unique",
            "unique(original_tmpl_id)",
            "This product has already been replaced.",
        ),
        (
            "replacement_unique",
            "unique(replacement_tmpl_id)",
            "This product is already the replacement of another product.",
        ),
        (
            "original_differs_from_replacement",
            "check(original_tmpl_id != replacement_tmpl_id)",
            "A product cannot replace itself.",
        ),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        # Freeze the reason name on the audit record.
        reasons = self.env["product.replacement.reason"].sudo()
        for vals in vals_list:
            if not vals.get("reason_name") and vals.get("reason_id"):
                vals["reason_name"] = reasons.browse(vals["reason_id"]).name
        return super().create(vals_list)

    @api.depends("original_tmpl_id", "replacement_tmpl_id")
    def _compute_display_name(self):
        for record in self:
            record.display_name = "%s → %s" % (
                record.original_tmpl_id.display_name or "",
                record.replacement_tmpl_id.display_name or "",
            )
