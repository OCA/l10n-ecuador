from odoo import _
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import Form

from odoo.addons.l10n_ec_account_edi.tests.sri_response import patch_service_sri
from odoo.addons.l10n_ec_account_edi.tests.test_edi_common import TestL10nECEdiCommon


@tagged("post_install_l10n", "post_install", "-at_install")
class TestL10nSaleWithhold(TestL10nECEdiCommon):
    @classmethod
    def setUpClass(
        cls,
        chart_template_ref="ec",
    ):
        super().setUpClass(chart_template_ref=chart_template_ref)
        cls.WizardWithhold = cls.env["l10n_ec.wizard.create.purchase.withhold"]
        cls.position_no_withhold = cls.env["account.fiscal.position"].create(
            {"name": "Withhold", "l10n_ec_avoid_withhold": True}
        )
        cls.position_require_withhold = cls.env["account.fiscal.position"].create(
            {"name": "Withhold", "l10n_ec_avoid_withhold": False}
        )
        cls.company.property_account_position_id = cls.position_require_withhold
        cls.chart_template = cls.env["account.chart.template"].with_company(cls.company)
        cls.tax_withhold_vat_100 = cls.chart_template.ref("tax_withhold_vat_100")
        cls.tax_withhold_profit_303 = cls.chart_template.ref("tax_withhold_profit_303")
        cls.journal_purchase_withhold = cls.chart_template.ref("purchase_withhold_ec")
        cls.journal_purchase_withhold.l10n_ec_emission_address_id = (
            cls.partner_contact.id
        )

    def _prepare_new_wizard_withhold_purchase(
        self,
        invoices,
        new_document_number,
        tax_withhold_vat=None,
        tax_withhold_profit=None,
        tax_support_withhold_vat=None,
        tax_support_withhold_profit=None,
    ):
        def add_line(tax, tax_support=None):
            with wizard.withhold_line_ids.new() as line:
                line.invoice_id = invoice
                line.tax_group_withhold_id = tax.tax_group_id
                line.tax_withhold_id = tax
                if tax_support:
                    line.l10n_ec_tax_support = tax_support

        wizard = Form(
            self.WizardWithhold.with_context(
                active_ids=invoices.ids, default_partner_id=invoices.partner_id.id
            )
        )
        invoice = invoices[0]
        wizard.issue_date = invoice.invoice_date
        wizard.journal_id = invoice.journal_id
        wizard.document_number = new_document_number
        wizard.journal_id = self.journal_purchase_withhold
        if tax_withhold_vat:
            add_line(tax_withhold_vat, tax_support=tax_support_withhold_vat)
        if tax_withhold_profit:
            add_line(tax_withhold_profit, tax_support=tax_support_withhold_profit)
        return wizard

    @patch_service_sri
    def test_01_l10n_ec_invoice_no_require_withhold(self):
        # withholding is not required by fiscal position
        self.partner_ruc.property_account_position_id = self.position_no_withhold
        invoice = self._l10n_ec_create_in_invoice(self.partner_ruc, auto_post=True)
        invoice2 = self._l10n_ec_create_in_invoice(self.partner_ruc, auto_post=True)
        self.assertFalse(invoice.l10n_ec_withhold_active)
        self.assertFalse(invoice2.l10n_ec_withhold_active)
        msj_expected = _(
            "Please select only invoice "
            "what satisfies the requirements for create withhold"
        )
        with self.assertRaisesRegex(UserError, msj_expected):
            (invoice | invoice2).action_try_create_ecuadorian_withhold()

    @patch_service_sri
    def test_02_l10n_ec_invoice_no_require_withhold_global(self):
        # withholding is not required by company, ignore fiscal position
        self.partner_ruc.property_account_position_id = self.position_require_withhold
        self.company.property_account_position_id = self.position_no_withhold
        invoice = self._l10n_ec_create_in_invoice(self.partner_ruc, auto_post=True)
        self.assertFalse(invoice.l10n_ec_withhold_active)
        msj_expected = _(
            "Please select only invoice "
            "what satisfies the requirements for create withhold"
        )
        with self.assertRaisesRegex(UserError, msj_expected):
            invoice.action_try_create_ecuadorian_withhold()

    @patch_service_sri
    def test_03_l10n_ec_invoice_no_tax_support(self):
        invoice = self._l10n_ec_create_in_invoice(auto_post=False)
        invoice.fiscal_position_id = self.position_require_withhold
        invoice.l10n_ec_tax_support = False
        msj_expected = "Please fill a Tax Support on Invoice"
        with self.assertRaisesRegex(UserError, msj_expected):
            invoice.action_post()

    @patch_service_sri
    def test_04_l10n_ec_withhold_without_lines(self):
        self.partner_ruc.property_account_position_id = self.position_require_withhold
        invoice = self._l10n_ec_create_in_invoice(self.partner_ruc, auto_post=True)
        self.assertTrue(invoice.l10n_ec_withhold_active)
        invoice.action_try_create_ecuadorian_withhold()
        wizard_form = self._prepare_new_wizard_withhold_purchase(invoice, "1-1-1")
        wizard = wizard_form.save()
        msj_expected = _("Please add some withholding lines before continue")
        with self.assertRaisesRegex(UserError, msj_expected):
            wizard.button_validate()

    @patch_service_sri
    def test_05_l10n_ec_new_electronic_withhold(self):
        self._setup_edi_company_ec()
        self.partner_ruc.property_account_position_id = self.position_require_withhold
        invoice_form = self._l10n_ec_create_form_move(
            move_type="in_invoice",
            internal_type="invoice",
            partner=self.partner_ruc,
            journal=self.journal_purchase,
            latam_document_type=self.env.ref("l10n_ec.ec_dt_01"),
        )
        invoice_form.l10n_ec_tax_support = "01"
        invoice_form.l10n_latam_document_number = "001-001-000000001"
        invoice_form.l10n_ec_electronic_authorization = (
            self.number_authorization_electronic
        )
        invoice = invoice_form.save()
        invoice.action_post()
        self.assertTrue(invoice.l10n_ec_withhold_active)
        invoice.action_try_create_ecuadorian_withhold()
        wizard_form = self._prepare_new_wizard_withhold_purchase(
            invoice,
            "001-001-000000001",
            tax_withhold_vat=self.tax_withhold_vat_100,
            tax_withhold_profit=self.tax_withhold_profit_303,
            tax_support_withhold_vat="01",
            tax_support_withhold_profit="01",
        )
        wizard = wizard_form.save()
        wizard.button_validate()
        withhold = invoice.l10n_ec_withhold_ids
        self.assertEqual(len(withhold), 1)
        self.assertEqual(withhold.l10n_ec_withholding_type, "purchase")
        self.assertEqual(withhold.state, "posted")
        self.assertEqual(invoice.payment_state, "partial")
        edi_doc = withhold._get_edi_document(self.edi_format)
        edi_doc._process_documents_web_services(with_commit=False)
        self.assertTrue(edi_doc.l10n_ec_xml_access_key)
        self.assertEqual(
            withhold.l10n_ec_xml_access_key, edi_doc.l10n_ec_xml_access_key
        )
        self.assertEqual(edi_doc.state, "sent")
        self.assertEqual(
            withhold.l10n_ec_authorization_date, edi_doc.l10n_ec_authorization_date
        )
        # Envio de email
        report_action = withhold.with_context(
            discard_logo_check=True
        ).action_invoice_sent()
        WizardMoveSend = self.env["account.move.send"].with_context(
            active_model=withhold._name, **report_action["context"]
        )
        WizardMoveSend.create({}).action_send_and_print()
        self.assertTrue(withhold.is_move_sent)

    @patch_service_sri
    def test_06_l10n_ec_check_withhold_values(self):
        # check withhold amount and base amount related with invoice
        self._setup_edi_company_ec()
        self.partner_ruc.property_account_position_id = self.position_require_withhold
        invoice_form = self._l10n_ec_create_form_move(
            move_type="in_invoice",
            internal_type="invoice",
            partner=self.partner_ruc,
            journal=self.journal_purchase,
            latam_document_type=self.env.ref("l10n_ec.ec_dt_01"),
        )
        invoice_form.l10n_ec_tax_support = "01"
        invoice_form.l10n_latam_document_number = "001-001-000000001"
        invoice_form.l10n_ec_electronic_authorization = (
            self.number_authorization_electronic
        )
        invoice = invoice_form.save()
        invoice.action_post()
        self.assertTrue(invoice.l10n_ec_withhold_active)
        wizard_form = self._prepare_new_wizard_withhold_purchase(
            invoice,
            "001-001-000000001",
            tax_withhold_vat=self.tax_withhold_vat_100,
            tax_withhold_profit=self.tax_withhold_profit_303,
            tax_support_withhold_vat="01",
            tax_support_withhold_profit="01",
        )
        wizard = wizard_form.save()
        wizard.button_validate()
        withhold = invoice.l10n_ec_withhold_ids
        self.assertEqual(len(withhold), 1)
        self.assertEqual(withhold.state, "posted")
        self.assertEqual(invoice.payment_state, "partial")
        # TODO: check values from some taxes
