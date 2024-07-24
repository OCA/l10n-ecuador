from dateutil.relativedelta import relativedelta

from odoo import _
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import Form

from odoo.addons.l10n_ec_account_edi.tests.sri_response import patch_service_sri
from odoo.addons.l10n_ec_account_edi.tests.test_edi_common import TestL10nECEdiCommon


@tagged("post_install_l10n", "post_install", "-at_install", "sale_withhold")
class TestL10nSaleWithhold(TestL10nECEdiCommon):
    @classmethod
    def setUpClass(
        cls,
        chart_template_ref="ec",
    ):
        super().setUpClass(chart_template_ref=chart_template_ref)
        cls.WizardWithhold = cls.env["l10n_ec.wizard.create.sale.withhold"]
        cls.position_no_withhold = cls.env["account.fiscal.position"].create(
            {"name": "Withhold", "l10n_ec_avoid_withhold": True}
        )
        cls.chart_template = cls.env["account.chart.template"].with_company(cls.company)
        cls.tax_sale_withhold_vat_50 = cls.chart_template.ref(
            "tax_sale_withhold_vat_50"
        )
        cls.tax_sale_withhold_vat_100 = cls.chart_template.ref(
            "tax_sale_withhold_vat_100"
        )
        cls.tax_sale_withhold_profit_303 = cls.chart_template.ref(
            "tax_withhold_profit_303"
        )

    @patch_service_sri
    def get_invoice(self, partner):
        """
        Create invoice
        """
        if not self.company.vat:
            self._setup_edi_company_ec()
        invoice = self._l10n_ec_prepare_edi_out_invoice(partner=partner, auto_post=True)
        edi_doc = invoice._get_edi_document(self.edi_format)
        edi_doc._process_documents_web_services(with_commit=False)
        return invoice

    def _prepare_new_wizard_withhold(
        self,
        invoices,
        new_document_number,
        electronic_authorization,
        tax_withhold_vat=None,
        tax_withhold_profit=None,
    ):
        def add_line(tax):
            with wizard.withhold_line_ids.new() as line:
                line.invoice_id = invoice
                line.tax_group_withhold_id = tax.tax_group_id
                line.tax_withhold_id = tax

        wizard = Form(self.WizardWithhold.with_context(active_ids=invoices.ids))
        invoice = invoices[0]
        wizard.issue_date = invoice.invoice_date
        wizard.journal_id = invoice.journal_id
        wizard.electronic_authorization = electronic_authorization
        wizard.document_number = new_document_number
        if tax_withhold_vat:
            add_line(tax_withhold_vat)
        if tax_withhold_profit:
            add_line(tax_withhold_profit)
        return wizard

    def test_l10n_ec_save_sale_withhold(self):
        """
        Normal save
        """
        partner = self.partner_with_email
        invoice = self.get_invoice(partner)
        wizard = self._prepare_new_wizard_withhold(
            invoice,
            "1-1-1",
            "1111111111",
            tax_withhold_vat=self.tax_sale_withhold_vat_100,
            tax_withhold_profit=self.tax_sale_withhold_profit_303,
        )
        self.assertEqual(wizard.partner_id, partner)
        self.assertEqual(wizard.document_number, "001-001-000000001")
        wizard.save().button_validate()
        sale_withhold = self.env["account.move"].search(
            [
                ("partner_id", "=", wizard.partner_id.id),
                ("ref", "=", wizard.document_number),
                ("l10n_ec_withholding_type", "=", "sale"),
                ("l10n_latam_internal_type", "=", "withhold"),
            ]
        )
        self.assertEqual(len(sale_withhold), 1)
        # Withhold of tax is 100% of tax amount of invoice
        for line in sale_withhold.l10n_ec_withhold_line_ids:
            for tax in line.tax_ids:
                if tax.tax_group_id.l10n_ec_type == "withhold_vat_sale":
                    self.assertEqual(
                        line.l10n_ec_withhold_tax_amount,
                        line.l10n_ec_invoice_withhold_id.amount_tax,
                    )
                if tax.tax_group_id.l10n_ec_type == "withhold_income_sale":
                    self.assertEqual(
                        line.l10n_ec_withhold_tax_amount,
                        line.l10n_ec_invoice_withhold_id.price_subtotal,
                    )

    def test_l10n_ec_fail_sale_withhold(self):
        """
        Fail when document number of withhold not has a valid format
        or
        Fail when invoice date not be less of withhold date
        """
        partner = self.partner_with_email
        invoice = self.get_invoice(partner)
        wizard = self._prepare_new_wizard_withhold(
            invoice,
            "1-1-1",
            "1234567890",
            tax_withhold_vat=self.tax_sale_withhold_vat_100,
        )
        # Bad format document number
        with self.assertRaises(UserError):
            wizard.document_number = "1"
        # Invoice date not be less of withhold date
        wizard.issue_date = invoice.invoice_date - relativedelta(days=1)
        with self.assertRaises(UserError):
            wizard.save().button_validate()

    def test_l10n_ec_authorization_sale_withhold(self):
        """
        Fail when authorization key not validate
        or authorization key not correspond to withhold
        or Fail when withhold not has detail
        """
        partner = self.partner_with_email
        invoice = self.get_invoice(partner)
        wizard = self._prepare_new_wizard_withhold(
            invoice,
            "1-1-1",
            "1234567890",
            tax_withhold_vat=self.tax_sale_withhold_vat_100,
        )
        with self.assertRaises(UserError):
            wizard.electronic_authorization = "2809202307123456789000120010020000"
        with self.assertRaises(UserError):
            wizard.electronic_authorization = (
                "2809202302123456789000120010020000122171234567815"
            )
        wizard.electronic_authorization = (
            "2809202307123456789000120010020000122171234567815"
        )
        # no lines, raise exception
        with self.assertRaises(UserError):
            wizard.save().button_validate()

    def test_l10n_ec_different_invoices_fail_withhold(self):
        """
        Fail when select two invoice of different customers
        """
        partner1 = self.partner_with_email
        partner2 = self.partner_ruc
        invoice1 = self.get_invoice(partner1)
        invoice2 = self.get_invoice(partner2)
        invoices = invoice1 + invoice2
        with self.assertRaises(UserError):
            Form(self.WizardWithhold.with_context(active_ids=invoices.ids))

    def test_l10n_ec_two_invoices_fail_withhold(self):
        """
        Fail when withhold not content selected invoices
        """
        partner1 = self.partner_with_email
        partner2 = self.partner_with_email
        invoice1 = self.get_invoice(partner1)
        invoice2 = self.get_invoice(partner2)
        invoices = invoice1 + invoice2
        wizard = self._prepare_new_wizard_withhold(
            invoices,
            "1-1-1",
            "1111111111",
            tax_withhold_vat=self.tax_sale_withhold_vat_100,
        )
        with wizard.withhold_line_ids.new() as line:
            line.invoice_id = invoice1
            line.tax_group_withhold_id = self.tax_sale_withhold_vat_100.tax_group_id
            line.tax_withhold_id = self.tax_sale_withhold_vat_100
        with self.assertRaises(UserError):
            wizard.save().button_validate()

    def test_l10n_ec_withhold_exist(self):
        """
        Fail when save duplicate withhold with same pather
        Both withhold has the same number: 001-001-000000001
        """
        partner1 = self.partner_with_email
        partner2 = self.partner_with_email
        invoice1 = self.get_invoice(partner1)
        invoice2 = self.get_invoice(partner2)
        wizard1 = self._prepare_new_wizard_withhold(
            invoice1,
            "1-1-1",
            "1111111111",
            tax_withhold_vat=self.tax_sale_withhold_vat_100,
        )
        wizard1.save().button_validate()
        wizard2 = self._prepare_new_wizard_withhold(
            invoice2,
            "1-1-1",
            "1111111111",
            tax_withhold_vat=self.tax_sale_withhold_vat_100,
        )
        with self.assertRaises(UserError):
            wizard2.save().button_validate()

    def test_l10n_ec_invoice_exist_in_withhold(self):
        """
        Fail when other invoice exist in different withhold
        """
        partner = self.partner_with_email
        invoice = self.get_invoice(partner)
        wizard1 = self._prepare_new_wizard_withhold(
            invoice,
            "1-1-1",
            "1111111111",
            tax_withhold_vat=self.tax_sale_withhold_vat_100,
        )
        # Create first withhold
        wizard1.save().button_validate()
        # Create other withhold with the same invoice
        wizard2 = self._prepare_new_wizard_withhold(
            invoice,
            "1-1-2",
            "1111111111",
            tax_withhold_vat=self.tax_sale_withhold_vat_100,
        )
        with self.assertRaises(UserError):
            wizard2.save().button_validate()

    def test_l10n_ec_fail_when_invoice_is_paid(self):
        """
        Fail when invoice is paid
        """
        partner = self.partner_with_email
        invoice = self.get_invoice(partner)
        invoice.write({"payment_state": "paid"})

        with self.assertRaises(UserError):
            Form(self.WizardWithhold.with_context(active_ids=invoice.ids))

    def test_l10n_ec_fail_when_invoice_no_require_withholding(self):
        self.partner_ruc.property_account_position_id = self.position_no_withhold
        invoice = self.get_invoice(self.partner_ruc)
        self.assertFalse(invoice.l10n_ec_withhold_active)
        msj_expected = _(
            "Please select only invoice "
            "what satisfies the requirements for create withhold"
        )
        with self.assertRaisesRegex(UserError, msj_expected):
            invoice.action_try_create_ecuadorian_withhold()

    def test_l10n_ec_sale_withhold_check_values_two_invoice(self):
        """
        Create withhold with two invoice
        check values concilied
        invoice1:
            total 100,
            tax 15,
            apply Withhold VAT 100%, profit 10%,
            total_withhold=25(15+10)
            Invoice residual = 115 - 25 = 90
        invoice2:
            total 100,
            tax 15,
            apply Withhold VAT 50%, profit 10%,
            total_withhold=17.5(7.5+10)
            Invoice residual = 115 - 17.5 = 97.5
        """
        self.product_a.list_price = 100
        partner = self.partner_with_email
        invoice1 = self.get_invoice(partner)
        invoice2 = self.get_invoice(partner)
        self.assertEqual(invoice1.amount_total, 115)
        self.assertEqual(invoice1.amount_tax, 15)
        self.assertEqual(invoice1.amount_residual, 115)
        self.assertEqual(invoice2.amount_total, 115)
        self.assertEqual(invoice2.amount_tax, 15)
        self.assertEqual(invoice2.amount_residual, 115)
        all_invoices = invoice1 + invoice2
        wizard = self._prepare_new_wizard_withhold(
            all_invoices,
            "1-1-1",
            "1111111111",
        )
        with wizard.withhold_line_ids.new() as line:
            line.invoice_id = invoice1
            line.tax_group_withhold_id = self.tax_sale_withhold_vat_100.tax_group_id
            line.tax_withhold_id = self.tax_sale_withhold_vat_100
        with wizard.withhold_line_ids.new() as line:
            line.invoice_id = invoice1
            line.tax_group_withhold_id = self.tax_sale_withhold_profit_303.tax_group_id
            line.tax_withhold_id = self.tax_sale_withhold_profit_303
        with wizard.withhold_line_ids.new() as line:
            line.invoice_id = invoice2
            line.tax_group_withhold_id = self.tax_sale_withhold_vat_50.tax_group_id
            line.tax_withhold_id = self.tax_sale_withhold_vat_50
        with wizard.withhold_line_ids.new() as line:
            line.invoice_id = invoice2
            line.tax_group_withhold_id = self.tax_sale_withhold_profit_303.tax_group_id
            line.tax_withhold_id = self.tax_sale_withhold_profit_303
        wizard.save().button_validate()
        sale_withhold = self.env["account.move"].search(
            [
                ("partner_id", "=", wizard.partner_id.id),
                ("ref", "=", wizard.document_number),
                ("l10n_ec_withholding_type", "=", "sale"),
                ("l10n_latam_internal_type", "=", "withhold"),
            ]
        )
        self.assertEqual(len(sale_withhold), 1)
        withholding_lines_invoice1 = self.env["account.move.line"].search(
            [
                ("move_id", "=", sale_withhold.id),
                ("l10n_ec_invoice_withhold_id", "=", invoice1.id),
                ("account_id.account_type", "=", "asset_receivable"),
            ]
        )
        withholding_lines_invoice2 = self.env["account.move.line"].search(
            [
                ("move_id", "=", sale_withhold.id),
                ("l10n_ec_invoice_withhold_id", "=", invoice2.id),
                ("account_id.account_type", "=", "asset_receivable"),
            ]
        )
        self.assertEqual(abs(withholding_lines_invoice1.balance), 25)
        self.assertEqual(abs(withholding_lines_invoice2.balance), 17.5)
        self.assertEqual(invoice1.amount_residual, 90)
        self.assertEqual(invoice2.amount_residual, 97.5)
        self.assertIn(
            withholding_lines_invoice1,
            invoice1.line_ids.matched_credit_ids.credit_move_id,
        )
        self.assertIn(
            withholding_lines_invoice2,
            invoice2.line_ids.matched_credit_ids.credit_move_id,
        )
