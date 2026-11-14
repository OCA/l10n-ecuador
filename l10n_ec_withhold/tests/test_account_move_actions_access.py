from odoo import Command
from odoo.tests import tagged

from odoo.addons.l10n_ec_account_edi.tests.test_edi_common import TestL10nECEdiCommon


@tagged("post_install_l10n", "post_install", "-at_install")
class TestAccountMoveActionsAccess(TestL10nECEdiCommon):
    """A billing user must open withhold actions without ``AccessError``.

    Regression test for the review fix: opening an ``ir.actions.actions``
    through ``env.ref(...).read()`` requires admin-level access to the action
    record, so a normal billing user got ``AccessError``. Resolving through
    ``env["ir.actions.actions"]._for_xml_id()`` sudo-reads a safe field subset
    and works for any internal user. The three openings below are the ones the
    module performs; if any of them goes back to ``env.ref``, this suite fails
    the way a billing clerk would.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.billing_user = cls.env["res.users"].create(
            {
                "name": "Billing Clerk",
                "login": "billing_clerk_withhold_test",
                "group_ids": [
                    Command.set(
                        [
                            cls.env.ref("base.group_user").id,
                            cls.env.ref("account.group_account_invoice").id,
                        ]
                    )
                ],
            }
        )

    def test_01_billing_user_resolves_withhold_actions(self):
        actions = self.env["ir.actions.actions"].with_user(self.billing_user)
        sale_action = actions._for_xml_id(
            "l10n_ec_withhold.l10n_ec_wizard_sale_withhold_action_window"
        )
        self.assertEqual(
            sale_action["res_model"], "l10n_ec.wizard.create.sale.withhold"
        )
        purchase_action = actions._for_xml_id(
            "l10n_ec_withhold.l10n_ec_wizard_purchase_withhold_action_window"
        )
        self.assertEqual(
            purchase_action["res_model"], "l10n_ec.wizard.create.purchase.withhold"
        )
        journal_action = actions._for_xml_id("account.action_move_journal_line")
        self.assertEqual(journal_action["res_model"], "account.move")

    def test_02_billing_user_opens_withhold_wizards(self):
        invoice = self._l10n_ec_create_in_invoice(self.partner_ruc, auto_post=False)
        invoice_as_clerk = invoice.with_user(self.billing_user)
        sale_action = invoice_as_clerk._action_create_sale_withhold_wizard()
        self.assertEqual(
            sale_action["res_model"], "l10n_ec.wizard.create.sale.withhold"
        )
        purchase_action = invoice_as_clerk._action_create_purchase_withhold_wizard()
        self.assertEqual(
            purchase_action["res_model"], "l10n_ec.wizard.create.purchase.withhold"
        )

    def test_03_billing_user_lists_withholds(self):
        invoice = self._l10n_ec_create_in_invoice(self.partner_ruc, auto_post=False)
        withhold = self._l10n_ec_create_in_invoice(self.partner_ruc, auto_post=False)
        invoice.write({"l10n_ec_withhold_ids": [Command.link(withhold.id)]})
        action = invoice.with_user(self.billing_user).action_show_l10n_ec_withholds()
        self.assertEqual(action["res_model"], "account.move")
        self.assertEqual(action["res_id"], withhold.id)
