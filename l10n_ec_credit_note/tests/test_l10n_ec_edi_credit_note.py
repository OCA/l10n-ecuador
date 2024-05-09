from odoo.tests import tagged

from odoo.addons.l10n_ec_account_edi.tests.test_edi_common import TestL10nECEdiCommon
from odoo.addons.stock_account.tests.test_stockvaluation import _create_accounting_data

FORM_ID = "account.view_move_form"


@tagged("post_install_l10n", "post_install", "-at_install")
class TestL10nClDte(TestL10nECEdiCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.discount_account_id = cls.env["account.account"].create(
            {
                "company_id": cls.company_data["company"].id,
                "name": "Discount Account",
                "account_type": "income",
                "code": "411041104110",
            }
        )
        cls.return_account_id = cls.env["account.account"].create(
            {
                "company_id": cls.company_data["company"].id,
                "name": "Return Account",
                "account_type": "income",
                "code": "411141114111",
            }
        )
        cls.company.write(
            {
                "l10n_ec_property_account_discount_id": cls.discount_account_id.id,
                "l10n_ec_property_account_return_id": cls.return_account_id.id,
            }
        )

        (
            cls.stock_input_account,
            cls.stock_output_account,
            cls.stock_valuation_account,
            cls.expense_account,
            cls.stock_journal,
        ) = _create_accounting_data(cls.env)

        cls.category = cls.env["product.category"].create(
            {
                "name": "Test Category",
                "property_cost_method": "average",
                "property_valuation": "real_time",
                "l10n_ec_property_account_return_id": cls.return_account_id,
                "l10n_ec_property_account_discount_id": cls.discount_account_id,
                "property_stock_account_input_categ_id": cls.stock_input_account.id,
                "property_stock_account_output_categ_id": cls.stock_output_account.id,
                "property_stock_valuation_account_id": cls.stock_valuation_account.id,
                "property_stock_journal": cls.stock_journal.id,
            }
        )

        cls.product = cls.env["product.product"].create(
            {
                "name": "Test Product",
                "detailed_type": "product",
                "categ_id": cls.category.id,
                "standard_price": 100,
            }
        )

    def _create_credit_note(self, credit_note_type, invoice, auto_post=True):
        reversal_wizard = self.env["account.move.reversal"].create(
            {
                "journal_id": invoice.journal_id.id,
                "move_ids": [(6, 0, invoice.ids)],
                "l10n_ec_type_credit_note": credit_note_type,
            }
        )
        if auto_post:
            reversal_wizard.modify_moves()
        else:
            reversal_wizard.refund_moves()
        return reversal_wizard

    def generate_credit_note(self, credit_note_type, product=None, auto_post=False):
        invoice = self._l10n_ec_prepare_edi_out_invoice(
            products=product, auto_post=auto_post
        )
        credit_note_wizard = self._create_credit_note(
            credit_note_type=credit_note_type, invoice=invoice, auto_post=auto_post
        )
        new_move_ids = credit_note_wizard.new_move_ids
        if auto_post:
            new_move_ids = invoice.reversal_move_id.filtered(
                lambda x: x.move_type == "out_refund"
            )
        return new_move_ids

    def test_action_action_reverse(self):
        invoice = self._l10n_ec_prepare_edi_out_invoice()
        action = invoice.action_reverse()
        view = self.env.ref("l10n_ec_credit_note.view_account_invoice_refund_sale").id
        self.assertEqual(action["res_model"], "account.move.reversal")
        self.assertEqual(action["views"], [(view, "form")])

    def test_create_invoice_and_credit_note_config_account_return(self):
        type_credit_notes = "return"
        new_move_ids = self.generate_credit_note(type_credit_notes)
        expected_account_id = self.company.l10n_ec_property_account_return_id
        for line in new_move_ids.mapped("line_ids").filtered(
            lambda x: x.display_type == "product"
        ):
            self.assertEqual(line.account_id, expected_account_id)

    def test_create_invoice_and_credit_note_config_account_discount(self):
        type_credit_notes = "discount"
        new_move_ids = self.generate_credit_note(type_credit_notes)
        expected_account_id = self.company.l10n_ec_property_account_discount_id
        for line in new_move_ids.mapped("line_ids").filtered(
            lambda x: x.display_type == "product"
        ):
            self.assertEqual(line.account_id, expected_account_id)

    def test_create_invoice_and_credit_note_category_return(self):
        new_move_ids = self.generate_credit_note("return", product=self.product)
        expected_account_id = self.category.l10n_ec_property_account_return_id
        for line in new_move_ids.mapped("line_ids").filtered(
            lambda x: x.display_type == "product"
        ):
            self.assertEqual(line.account_id, expected_account_id)

    def test_create_invoice_and_credit_note_category_discount(self):
        new_move_ids = self.generate_credit_note("discount", product=self.product)
        expected_account_id = self.category.l10n_ec_property_account_discount_id
        for line in new_move_ids.mapped("line_ids").filtered(
            lambda x: x.display_type == "product"
        ):
            self.assertEqual(line.account_id, expected_account_id)

    def test_create_invoice_and_credit_note_product_return(self):
        self.product.write(
            {"l10n_ec_property_account_return_id": self.return_account_id}
        )
        new_move_ids = self.generate_credit_note("return", product=self.product)
        expected_account_id = self.product.l10n_ec_property_account_return_id
        for line in new_move_ids.mapped("line_ids").filtered(
            lambda x: x.display_type == "product"
        ):
            self.assertEqual(line.account_id, expected_account_id)

    def test_create_invoice_and_credit_note_product_discount(self):
        self.product.write(
            {"l10n_ec_property_account_discount_id": self.discount_account_id}
        )
        new_move_ids = self.generate_credit_note("discount", product=self.product)
        expected_account_id = self.product.l10n_ec_property_account_discount_id
        for line in new_move_ids.mapped("line_ids").filtered(
            lambda x: x.display_type == "product"
        ):
            self.assertEqual(line.account_id, expected_account_id)

    def test_create_invoice_and_credit_note_product_discount_post(self):
        self._setup_edi_company_ec()
        self.company.write({"anglo_saxon_accounting": True})
        self.product.write(
            {"l10n_ec_property_account_discount_id": self.discount_account_id}
        )
        new_move_ids = self.generate_credit_note("discount", product=self.product)
        new_move_ids.action_post()
        expected_account_id = self.product.l10n_ec_property_account_discount_id
        for line in new_move_ids.mapped("line_ids").filtered(
            lambda x: x.display_type == "product"
        ):
            self.assertEqual(line.account_id, expected_account_id)
        cogs_lines = new_move_ids.mapped("line_ids").filtered(
            lambda x: x.display_type == "cogs"
        )
        self.assertFalse(cogs_lines)

    def test_create_invoice_and_credit_note_discount_anglo(self):
        self._setup_edi_company_ec()
        self.company.write({"anglo_saxon_accounting": True})

        new_move_ids = self.generate_credit_note(
            "return", product=self.product, auto_post=True
        )

        self.assertEqual(new_move_ids.state, "posted")
        cogs_lines = new_move_ids.mapped("line_ids").filtered(
            lambda x: x.display_type == "cogs"
        )
        self.assertTrue(cogs_lines)
        new_move_ids = self.generate_credit_note(
            "discount", product=self.product, auto_post=True
        )
        self.assertEqual(new_move_ids.state, "posted")
        cogs_lines = new_move_ids.mapped("line_ids").filtered(
            lambda x: x.display_type == "cogs"
        )
        self.assertFalse(cogs_lines)
