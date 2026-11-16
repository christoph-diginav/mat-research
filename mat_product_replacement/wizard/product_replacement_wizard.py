from odoo import api, fields, models


class ProductReplacementWizard(models.TransientModel):
    _name = "product.replacement.wizard"
    _description = "Replace Product"

    product_tmpl_id = fields.Many2one(
        "product.template",
        string="Product to Replace",
        required=True,
    )
    replacement_name = fields.Char(
        string="Replacement Name",
        required=True,
    )
    replacement_default_code = fields.Char(string="Replacement Internal Reference")
    reason_id = fields.Many2one(
        "product.replacement.reason",
        string="Reason",
        required=True,
    )
    note = fields.Text(string="Explanation")

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        context = self.env.context
        if context.get("active_model") == "product.template" and context.get("active_id"):
            product = self.env["product.template"].browse(context["active_id"])
            if "product_tmpl_id" in fields_list and not defaults.get("product_tmpl_id"):
                defaults["product_tmpl_id"] = product.id
            if "replacement_name" in fields_list and not defaults.get("replacement_name"):
                defaults["replacement_name"] = product.name
        return defaults

    def action_replace(self):
        self.ensure_one()
        replacement = self.product_tmpl_id.replace_product(
            self.reason_id,
            note=self.note,
            name=self.replacement_name,
            default_code=self.replacement_default_code,
        )
        return {
            "type": "ir.actions.act_window",
            "res_model": "product.template",
            "res_id": replacement.id,
            "view_mode": "form",
            "target": "current",
        }
