from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

REPLACEMENT_MANAGER_GROUP = "mat_product_replacement.group_product_replacement_manager"

# Derived from the audit records only; never writable by hand.
PROTECTED_FIELDS = ("replacement_state", "replaced_by_id", "replaces_id")


class ProductTemplate(models.Model):
    _inherit = "product.template"

    replacement_as_original_ids = fields.One2many(
        "product.replacement",
        "original_tmpl_id",
        string="Replacement (as original)",
        copy=False,
    )
    replacement_as_replacement_ids = fields.One2many(
        "product.replacement",
        "replacement_tmpl_id",
        string="Replacement (as replacement)",
        copy=False,
    )
    replaced_by_id = fields.Many2one(
        "product.template",
        string="Replaced By",
        compute="_compute_replacement_links",
        store=True,
        copy=False,
    )
    replaces_id = fields.Many2one(
        "product.template",
        string="Replaces",
        compute="_compute_replacement_links",
        store=True,
        copy=False,
    )
    replacement_state = fields.Selection(
        [
            ("normal", "Regular"),
            ("new", "New"),
            ("deprecated", "Deprecated"),
        ],
        string="Replacement Status",
        compute="_compute_replacement_links",
        store=True,
        copy=False,
        index=True,
        help="Regular: never involved in a replacement.\n"
        "New: created as the replacement of another product.\n"
        "Deprecated: replaced by another product.",
    )
    replacement_log_ids = fields.Many2many(
        "product.replacement",
        string="Replacement History",
        compute="_compute_replacement_log_ids",
    )

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------

    @api.depends(
        "replacement_as_original_ids.replacement_tmpl_id",
        "replacement_as_replacement_ids.original_tmpl_id",
    )
    def _compute_replacement_links(self):
        for template in self:
            template_sudo = template.sudo()
            as_original = template_sudo.replacement_as_original_ids[:1]
            as_replacement = template_sudo.replacement_as_replacement_ids[:1]
            template.replaced_by_id = as_original.replacement_tmpl_id
            template.replaces_id = as_replacement.original_tmpl_id
            if as_original:
                # A replacement that is itself replaced later (A -> B -> C)
                # becomes deprecated: being an original takes precedence.
                template.replacement_state = "deprecated"
            elif as_replacement:
                template.replacement_state = "new"
            else:
                template.replacement_state = "normal"

    @api.depends("replacement_as_original_ids", "replacement_as_replacement_ids")
    def _compute_replacement_log_ids(self):
        for template in self:
            template_sudo = template.sudo()
            template.replacement_log_ids = (
                template_sudo.replacement_as_original_ids
                | template_sudo.replacement_as_replacement_ids
            )

    # ------------------------------------------------------------------
    # Protection of the derived fields
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        # Values passed by hand are ignored so that the computes decide.
        vals_list = [
            {key: value for key, value in vals.items() if key not in PROTECTED_FIELDS}
            for vals in vals_list
        ]
        return super().create(vals_list)

    def write(self, vals):
        if any(fname in vals for fname in PROTECTED_FIELDS):
            raise UserError(
                _(
                    "The replacement status and links are set by the Replace"
                    " action only and cannot be edited."
                )
            )
        return super().write(vals)

    # ------------------------------------------------------------------
    # Replacement
    # ------------------------------------------------------------------

    def _check_replacement_allowed(self, reason):
        """Raise if the current user may not replace this product now."""
        self.ensure_one()
        if not self.env.user.has_group(REPLACEMENT_MANAGER_GROUP):
            raise AccessError(
                _(
                    "Only users with the access right \"Product Replacement:"
                    " Manager\" can replace a product."
                )
            )
        if not reason or len(reason) != 1:
            raise UserError(_("A reason is required to replace a product."))
        if not reason.active:
            raise UserError(
                _("The reason \"%(reason)s\" is archived.", reason=reason.name)
            )
        if not self.active:
            raise UserError(_("An archived product cannot be replaced."))
        if self.product_variant_count != 1:
            raise UserError(
                _(
                    "Only products with exactly one variant can be replaced."
                    " \"%(product)s\" has %(count)s.",
                    product=self.display_name,
                    count=self.product_variant_count,
                )
            )
        existing = (
            self.env["product.replacement"]
            .sudo()
            .search([("original_tmpl_id", "=", self.id)], limit=1)
        )
        if existing:
            raise UserError(
                _(
                    "\"%(product)s\" has already been replaced by"
                    " \"%(replacement)s\". A product can be replaced only once.",
                    product=self.display_name,
                    replacement=existing.replacement_tmpl_id.display_name,
                )
            )

    def replace_product(self, reason, note=False, name=False, default_code=False):
        """Replace this product by a new copy of itself.

        The replacement is an ordinary duplicate (``copy()``), so stock and
        existing documents stay on the original, which is left active.

        :param reason: ``product.replacement.reason`` record (required)
        :param str note: optional free-text explanation
        :param str name: name of the replacement; standard "(copy)" if empty
        :param str default_code: internal reference of the replacement
        :return: the replacement ``product.template``

        Authorisation is the membership of the replacement group, checked
        here on the real user. The steps then run as superuser, so that the
        group alone decides who can replace, independently of the product
        and audit access rights. ``sudo()`` keeps the user id, so the copy,
        the audit record and the chatter notes are attributed to that user.

        All steps run in one savepoint: if any of them fails, including the
        database constraints checked when the savepoint is released, nothing
        is kept, even if the caller catches the exception.
        """
        self.ensure_one()
        self._check_replacement_allowed(reason)
        note = (note or "").strip() or False
        name = (name or "").strip()
        default_code = (default_code or "").strip()

        with self.env.cr.savepoint():
            original = self.sudo()
            # 1. Create the replacement first, so that it does not inherit
            #    anything set on the original in the next steps.
            replacement = original.copy(default={"name": name} if name else None)
            if default_code:
                replacement.default_code = default_code
            # 2. Audit record: links and statuses are computed from it. Its
            #    unique constraint is the final guard against a product being
            #    replaced twice, also by two users at the same time.
            self.env["product.replacement"].sudo().create(
                {
                    "original_tmpl_id": original.id,
                    "replacement_tmpl_id": replacement.id,
                    "user_id": self.env.uid,
                    "date": fields.Datetime.now(),
                    "reason_id": reason.id,
                    "reason_name": reason.name,
                    "note": note,
                }
            )
            # 3. Nudge on new sales orders, then trace in both chatters.
            original._set_deprecation_sale_warning(replacement)
            original._post_replacement_messages(replacement, reason, note)
        return replacement.with_env(self.env)

    def _set_deprecation_sale_warning(self, replacement):
        """Warn (not block) when the deprecated product is put on an order.

        V1: an existing warning on the original is overwritten.
        """
        self.ensure_one()
        if "sale_line_warn" not in self._fields:
            return
        self.write(
            {
                "sale_line_warn": "warning",
                "sale_line_warn_msg": _(
                    "%(original)s is deprecated and has been replaced by"
                    " %(replacement)s.",
                    original=self.display_name,
                    replacement=replacement.display_name,
                ),
            }
        )

    def _post_replacement_messages(self, replacement, reason, note):
        self.ensure_one()
        details = Markup("<br/>%s %s") % (_("Reason:"), reason.name)
        if note:
            details += Markup("<br/>%s %s") % (_("Context:"), note)
        self.message_post(
            body=Markup("%s %s") % (
                _("Deprecated and replaced by"),
                replacement._get_html_link(),
            ) + details,
            subtype_xmlid="mail.mt_note",
        )
        replacement.message_post(
            body=Markup("%s %s") % (
                _("Created as the replacement of"),
                self._get_html_link(),
            ) + details,
            subtype_xmlid="mail.mt_note",
        )
