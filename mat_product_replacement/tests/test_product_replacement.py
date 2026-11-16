from unittest.mock import patch

from psycopg2 import IntegrityError

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user, tagged
from odoo.tools import mute_logger

MANAGER_GROUP = "mat_product_replacement.group_product_replacement_manager"


@tagged("post_install", "-at_install")
class TestProductReplacement(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(
            cls.env,
            login="replacement_manager",
            groups="base.group_user,%s" % MANAGER_GROUP,
        )
        # Can create and edit products, but is not authorised to replace them.
        cls.sales_manager = new_test_user(
            cls.env,
            login="replacement_sales_manager",
            groups="base.group_user,sales_team.group_sale_manager",
        )
        cls.Replacement = cls.env["product.replacement"]
        cls.Template = cls.env["product.template"]
        cls.reason = cls.env["product.replacement.reason"].create(
            {"name": "Test reason: supplier discontinued"}
        )
        product_vals = {"name": "Buffer Solution pH 7", "default_code": "BUF-7"}
        if "is_storable" in cls.Template._fields:
            product_vals["is_storable"] = True
        cls.product = cls.Template.create(product_vals)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _replace(self, product=None, user=None, **kwargs):
        """Run the replacement as ``user`` and return it in the test env."""
        product = product or self.product
        replacement = product.with_user(user or self.manager).replace_product(
            self.reason, **kwargs
        )
        return self.Template.browse(replacement.id)

    def _log_of(self, product):
        return self.Replacement.search([("original_tmpl_id", "=", product.id)])

    def _count_templates(self):
        return self.Template.with_context(active_test=False).search_count([])

    # ------------------------------------------------------------------
    # Links, statuses, audit
    # ------------------------------------------------------------------

    def test_links_in_both_directions_and_statuses(self):
        self.assertEqual(self.product.replacement_state, "normal")

        replacement = self._replace(name="Buffer Solution pH 7 v2", default_code="BUF-7-V2")

        self.assertTrue(replacement)
        self.assertNotEqual(replacement, self.product)
        self.assertEqual(replacement.name, "Buffer Solution pH 7 v2")
        self.assertEqual(replacement.default_code, "BUF-7-V2")
        self.assertEqual(self.product.replaced_by_id, replacement)
        self.assertEqual(replacement.replaces_id, self.product)
        self.assertFalse(self.product.replaces_id)
        self.assertFalse(replacement.replaced_by_id)
        self.assertEqual(self.product.replacement_state, "deprecated")
        self.assertEqual(replacement.replacement_state, "new")

    def test_audit_record_who_when_why(self):
        before = fields.Datetime.now()

        replacement = self._replace(note="  Catalogue number 4471 was withdrawn.  ")

        log = self._log_of(self.product)
        self.assertEqual(len(log), 1)
        self.assertEqual(log.replacement_tmpl_id, replacement)
        self.assertEqual(log.user_id, self.manager)
        self.assertGreaterEqual(log.date, before)
        self.assertEqual(log.reason_id, self.reason)
        self.assertEqual(log.reason_name, "Test reason: supplier discontinued")
        self.assertEqual(log.note, "Catalogue number 4471 was withdrawn.")
        self.assertEqual(self.product.replacement_log_ids, log)
        self.assertEqual(replacement.replacement_log_ids, log)
        self.assertTrue(
            any(
                "Deprecated and replaced by" in (message.body or "")
                for message in self.product.message_ids
            ),
            "The original should have a chatter note about its replacement.",
        )
        self.assertTrue(
            any(
                "Created as the replacement of" in (message.body or "")
                for message in replacement.message_ids
            ),
            "The replacement should have a chatter note about its origin.",
        )
        for product in (self.product, replacement):
            self.assertTrue(
                any(
                    "Context: Catalogue number 4471 was withdrawn." in (message.body or "")
                    for message in product.message_ids
                ),
                "The explanation should be shown after \"Context:\".",
            )

    def test_chatter_has_no_context_line_without_explanation(self):
        replacement = self._replace()

        for product in (self.product, replacement):
            bodies = [message.body or "" for message in product.message_ids]
            self.assertTrue(any("Reason:" in body for body in bodies))
            self.assertFalse(any("Context:" in body for body in bodies))

    def test_renaming_a_reason_does_not_rewrite_history(self):
        self._replace()
        log = self._log_of(self.product)

        self.reason.name = "Renamed afterwards"

        self.assertEqual(log.reason_name, "Test reason: supplier discontinued")
        self.assertEqual(log.reason_id.name, "Renamed afterwards")

    # ------------------------------------------------------------------
    # Authorisation
    # ------------------------------------------------------------------

    def test_unauthorised_user_cannot_replace(self):
        templates_before = self._count_templates()

        with self.assertRaises(AccessError):
            self.product.with_user(self.sales_manager).replace_product(self.reason)
        with self.assertRaises(AccessError):
            self.env["product.replacement.wizard"].with_user(self.sales_manager).create(
                {
                    "product_tmpl_id": self.product.id,
                    "replacement_name": "Not allowed",
                    "reason_id": self.reason.id,
                }
            )

        self.assertEqual(self._count_templates(), templates_before)
        self.assertFalse(self._log_of(self.product))
        self.assertEqual(self.product.replacement_state, "normal")

    def test_group_is_manageable_from_the_user_form(self):
        """The group must be a named access right, not a debug-only checkbox.

        A categorised group that forms a chain on its own is exposed on
        res.users as a ``sel_groups_<id>`` selection in the Access Rights tab.
        """
        group = self.env.ref(MANAGER_GROUP)
        self.assertTrue(group.category_id)
        self.assertTrue(group.category_id.parent_id)
        user_fields = self.env["res.users"].fields_get()
        self.assertIn("sel_groups_%s" % group.id, user_fields)
        self.assertNotIn("in_group_%s" % group.id, user_fields)

    def test_audit_record_cannot_be_created_or_changed_by_hand(self):
        self._replace()
        log = self._log_of(self.product).with_user(self.manager)
        other = self.product.copy()

        with self.assertRaises(AccessError):
            log.write({"note": "Rewritten"})
        with self.assertRaises(AccessError):
            log.unlink()
        with self.assertRaises(AccessError):
            self.Replacement.with_user(self.manager).create(
                {
                    "original_tmpl_id": other.id,
                    "replacement_tmpl_id": self.product.id,
                    "reason_id": self.reason.id,
                }
            )

    def test_status_and_links_cannot_be_edited_by_hand(self):
        other = self.product.copy()

        with self.assertRaises(UserError):
            self.product.write({"replacement_state": "deprecated"})
        with self.assertRaises(UserError):
            self.product.write({"replaced_by_id": other.id})

        created = self.Template.create(
            {"name": "Created with a status", "replacement_state": "new"}
        )
        self.assertEqual(created.replacement_state, "normal")

    # ------------------------------------------------------------------
    # Repeated replacement
    # ------------------------------------------------------------------

    def test_product_cannot_be_replaced_twice(self):
        self._replace()
        templates_after_first = self._count_templates()

        with self.assertRaises(UserError):
            self._replace()

        self.assertEqual(len(self._log_of(self.product)), 1)
        self.assertEqual(self._count_templates(), templates_after_first)

    def test_database_blocks_a_second_replacement(self):
        """The unique constraint holds even if the Python guard is bypassed."""
        self._replace()
        other = self.product.copy()

        with mute_logger("odoo.sql_db"), self.assertRaises(IntegrityError):
            self.Replacement.create(
                {
                    "original_tmpl_id": self.product.id,
                    "replacement_tmpl_id": other.id,
                    "reason_id": self.reason.id,
                }
            )

    def test_replacement_can_itself_be_replaced(self):
        second = self._replace()

        third = self._replace(product=second)

        self.assertEqual(self.product.replaced_by_id, second)
        self.assertEqual(self.product.replacement_state, "deprecated")
        self.assertEqual(second.replaces_id, self.product)
        self.assertEqual(second.replaced_by_id, third)
        self.assertEqual(second.replacement_state, "deprecated")
        self.assertEqual(third.replaces_id, second)
        self.assertEqual(third.replacement_state, "new")

    # ------------------------------------------------------------------
    # Original is preserved
    # ------------------------------------------------------------------

    def test_original_stays_active_and_keeps_its_stock(self):
        variant = self.product.product_variant_id
        location = self.env.ref("stock.stock_location_stock")
        self.env["stock.quant"]._update_available_quantity(variant, location, 10.0)

        replacement = self._replace()

        self.assertTrue(self.product.active)
        self.assertTrue(variant.active)
        self.assertEqual(self.product.product_variant_id, variant)
        quants = self.env["stock.quant"].search(
            [("location_id", "=", location.id), ("product_id", "=", variant.id)]
        )
        self.assertEqual(sum(quants.mapped("quantity")), 10.0)
        self.assertFalse(
            self.env["stock.quant"].search_count(
                [("product_id", "in", replacement.product_variant_ids.ids)]
            ),
            "No stock may be moved to the replacement.",
        )

    def test_existing_sales_order_stays_on_the_original(self):
        variant = self.product.product_variant_id
        partner = self.env["res.partner"].create({"name": "Lab Customer"})
        order = self.env["sale.order"].create(
            {
                "partner_id": partner.id,
                "order_line": [
                    Command.create({"product_id": variant.id, "product_uom_qty": 2}),
                ],
            }
        )

        replacement = self._replace()

        self.assertEqual(order.order_line.product_id, variant)
        self.assertFalse(
            self.env["sale.order.line"].search_count(
                [("product_id", "in", replacement.product_variant_ids.ids)]
            ),
            "No order line may be moved to the replacement.",
        )

    # ------------------------------------------------------------------
    # Ordinary duplication
    # ------------------------------------------------------------------

    def test_ordinary_duplication_is_unchanged(self):
        duplicate = self.product.copy()

        self.assertEqual(duplicate.name, "Buffer Solution pH 7 (copy)")
        self.assertEqual(duplicate.replacement_state, "normal")
        self.assertFalse(duplicate.replaces_id)
        self.assertFalse(duplicate.replaced_by_id)
        self.assertEqual(self.product.replacement_state, "normal")
        self.assertFalse(self.product.replaced_by_id)
        self.assertFalse(
            self.Replacement.search_count(
                [
                    "|",
                    ("original_tmpl_id", "in", (self.product | duplicate).ids),
                    ("replacement_tmpl_id", "in", (self.product | duplicate).ids),
                ]
            )
        )

    def test_duplicates_of_replaced_products_carry_no_link(self):
        replacement = self._replace()

        duplicate_of_deprecated = self.product.copy()
        duplicate_of_new = replacement.copy()

        for duplicate in (duplicate_of_deprecated, duplicate_of_new):
            self.assertEqual(duplicate.replacement_state, "normal")
            self.assertFalse(duplicate.replaces_id)
            self.assertFalse(duplicate.replaced_by_id)
        self.assertEqual(self.product.replaced_by_id, replacement)
        self.assertEqual(len(self._log_of(self.product)), 1)

    # ------------------------------------------------------------------
    # Atomicity
    # ------------------------------------------------------------------

    def test_failed_replacement_leaves_no_partial_changes(self):
        """Fail at the very last step and check that nothing is kept.

        The exception is caught by hand on purpose (no ``assertRaises``, which
        would roll back by itself): what is tested is the savepoint of
        ``replace_product``.
        """
        templates_before = self._count_templates()
        messages_before = len(self.product.message_ids)
        has_sale_warning = "sale_line_warn" in self.Template._fields
        warning_before = self.product.sale_line_warn if has_sale_warning else None

        template_class = self.env.registry["product.template"]
        with patch.object(
            template_class,
            "_post_replacement_messages",
            side_effect=UserError("Simulated failure"),
        ):
            try:
                self._replace(name="Must not exist")
            except UserError as error:
                self.assertIn("Simulated failure", str(error))
            else:
                self.fail("The replacement should have failed.")

        self.env.invalidate_all()
        self.assertEqual(self._count_templates(), templates_before)
        self.assertFalse(self.Template.search([("name", "=", "Must not exist")]))
        self.assertFalse(self._log_of(self.product))
        self.assertEqual(self.product.replacement_state, "normal")
        self.assertFalse(self.product.replaced_by_id)
        self.assertEqual(len(self.product.message_ids), messages_before)
        if has_sale_warning:
            self.assertEqual(self.product.sale_line_warn, warning_before)

        # The product is still replaceable afterwards.
        replacement = self._replace()
        self.assertEqual(self.product.replaced_by_id, replacement)

    # ------------------------------------------------------------------
    # Scope and guards
    # ------------------------------------------------------------------

    def test_product_with_several_variants_is_rejected(self):
        attribute = self.env["product.attribute"].create(
            {
                "name": "Test Volume",
                "value_ids": [
                    Command.create({"name": "100 ml"}),
                    Command.create({"name": "500 ml"}),
                ],
            }
        )
        multi_variant = self.Template.create(
            {
                "name": "Ethanol",
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": attribute.id,
                            "value_ids": [Command.set(attribute.value_ids.ids)],
                        }
                    ),
                ],
            }
        )
        self.assertEqual(multi_variant.product_variant_count, 2)

        with self.assertRaises(UserError):
            self._replace(product=multi_variant)

        self.assertFalse(self._log_of(multi_variant))

    def test_archived_product_and_archived_reason_are_rejected(self):
        archived = self.Template.create({"name": "Archived product", "active": False})
        with self.assertRaises(UserError):
            self._replace(product=archived)

        self.reason.active = False
        with self.assertRaises(UserError):
            self._replace()
        self.assertFalse(self._log_of(self.product))

    # ------------------------------------------------------------------
    # Sales warning
    # ------------------------------------------------------------------

    def test_sales_warning_is_set_on_the_original_only(self):
        if "sale_line_warn" not in self.Template._fields:
            self.skipTest("Sales warnings are not available on products.")

        replacement = self._replace(name="Buffer Solution pH 7 v2")

        self.assertEqual(self.product.sale_line_warn, "warning")
        self.assertIn("Buffer Solution pH 7 v2", self.product.sale_line_warn_msg)
        self.assertEqual(replacement.sale_line_warn, "no-message")
        self.assertFalse(replacement.sale_line_warn_msg)

    # ------------------------------------------------------------------
    # Reasons
    # ------------------------------------------------------------------

    def test_used_reason_cannot_be_deleted(self):
        unused = self.env["product.replacement.reason"].create({"name": "Test reason: unused"})
        self._replace()

        with self.assertRaises(UserError):
            self.reason.unlink()
        unused.unlink()
        self.assertFalse(unused.exists())
        self.assertTrue(self.reason.exists())

    def test_reason_names_are_unique_ignoring_case(self):
        with self.assertRaises(ValidationError):
            self.env["product.replacement.reason"].create(
                {"name": "  test REASON: supplier discontinued "}
            )

    # ------------------------------------------------------------------
    # Wizard
    # ------------------------------------------------------------------

    def test_wizard_replaces_the_active_product(self):
        wizard = (
            self.env["product.replacement.wizard"]
            .with_user(self.manager)
            .with_context(active_model="product.template", active_id=self.product.id)
            .create({"reason_id": self.reason.id, "note": "Through the wizard"})
        )
        self.assertEqual(wizard.product_tmpl_id, self.product)
        self.assertEqual(wizard.replacement_name, "Buffer Solution pH 7")
        wizard.replacement_name = "Buffer Solution pH 7 v2"

        action = wizard.action_replace()

        replacement = self.Template.browse(action["res_id"])
        self.assertEqual(action["res_model"], "product.template")
        self.assertEqual(replacement.name, "Buffer Solution pH 7 v2")
        self.assertEqual(self.product.replaced_by_id, replacement)
        self.assertEqual(self._log_of(self.product).note, "Through the wizard")
