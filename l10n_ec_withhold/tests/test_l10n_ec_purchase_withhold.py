from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import Form, tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.l10n_ec_account_edi.models.account_edi_document import (
    AccountEdiDocument,
)
from odoo.addons.l10n_ec_account_edi.tests.sri_response import patch_service_sri
from odoo.addons.l10n_ec_account_edi.tests.test_edi_common import TestL10nECEdiCommon


@tagged("post_install_l10n", "post_install", "-at_install")
class TestL10nPurchaseWithhold(TestL10nECEdiCommon):
    @classmethod
    @AccountTestInvoicingCommon.setup_country("ec")
    @AccountTestInvoicingCommon.setup_chart_template("ec")
    def setUpClass(cls):
        # 19.0 ``setUpClass()`` takes no arguments: country and chart template
        # are set by decorators, not by a ``chart_template_ref`` parameter.
        super().setUpClass()
        cls.WizardWithhold = cls.env["l10n_ec.wizard.create.purchase.withhold"]
        cls.position_no_withhold = cls.env["account.fiscal.position"].create(
            {"name": "Withhold", "l10n_ec_avoid_withhold": True}
        )
        cls.position_require_withhold = cls.env["account.fiscal.position"].create(
            {"name": "Withhold", "l10n_ec_avoid_withhold": False}
        )
        cls.company.property_account_position_id = cls.position_require_withhold
        cls.chart_template = cls.env["account.chart.template"].with_company(cls.company)
        cls.tax_vat = cls.chart_template.ref("tax_vat_510_sup_01")
        cls.tax_withhold_vat_100 = cls.chart_template.ref("tax_withhold_vat_100")
        cls.tax_withhold_profit_303 = cls.chart_template.ref("tax_withhold_profit_303")
        cls.journal_purchase_withhold = cls.chart_template.ref("purchase_withhold_ec")
        cls.journal_purchase_withhold.l10n_ec_emission_address_id = (
            cls.partner_contact.id
        )
        # Shadow the inherited ``journal_purchase`` on purpose. The EC chart
        # template ships two ``type = 'purchase'`` journals: the ordinary
        # vendor-bill one and ``purchase_liquidation_ec``, which
        # ``l10n_ec_account_edi`` reserves for ``purchase_liquidation``
        # documents (its ``_search_default_journal`` and
        # ``_compute_suitable_journal_ids`` filter on
        # ``l10n_ec_is_purchase_liquidation``). 17.0 used
        # ``company_data["default_journal_purchase"]``, i.e. the ordinary one,
        # and that is also what 19.0's default-journal search resolves for an
        # ``ec_dt_01`` (Factura). ``TestL10nECCommon.journal_purchase`` points
        # at the liquidation journal, so without this shadow every test below
        # would silently post in the wrong journal.
        # Shadowing also makes the inherited ``_setup_edi_company_ec()``
        # configure this journal (emission address, SRI payment method, entity
        # and emission) instead of the liquidation one.
        cls.journal_purchase = cls.company_data["default_journal_purchase"]

    def test_00_purchase_journal_is_the_vendor_bill_one(self):
        """Pin which journal these tests post their vendor bills in.

        Guards the deliberate ``cls.journal_purchase`` shadow above: these tests
        must keep running against the ordinary vendor-bill journal, not against
        ``purchase_liquidation_ec``.
        """
        self.assertEqual(
            self.journal_purchase, self.company_data["default_journal_purchase"]
        )
        self.assertFalse(self.journal_purchase.l10n_ec_is_purchase_liquidation)
        self.assertNotEqual(
            self.journal_purchase, self.chart_template.ref("purchase_liquidation_ec")
        )

    def _prepare_new_wizard_withhold_purchase(
        self,
        invoices,
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
        invoice = self._l10n_ec_create_in_invoice(
            self.partner_ruc,
            auto_post=True,
            l10n_latam_document_number="001-001-000000001",
        )
        invoice2 = self._l10n_ec_create_in_invoice(
            self.partner_ruc,
            auto_post=True,
            l10n_latam_document_number="001-001-000000002",
        )
        self.assertFalse(invoice.l10n_ec_withhold_active)
        self.assertFalse(invoice2.l10n_ec_withhold_active)
        msj_expected = self.env._(
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
        msj_expected = self.env._(
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
        wizard_form = self._prepare_new_wizard_withhold_purchase(invoice)
        wizard = wizard_form.save()
        msj_expected = self.env._("Please add some withholding lines before continue")
        with self.assertRaisesRegex(UserError, msj_expected):
            wizard.button_validate()

    @patch_service_sri
    def test_04_l10n_ec_withhold_without_taxes(self):
        """
        Create a Invoice without taxes, and try create withhold
        a exception must be raised because the base amount is zero
        """
        self._setup_edi_company_ec()
        self.partner_ruc.property_account_position_id = self.position_require_withhold
        # invoice without taxes
        invoice = self._l10n_ec_create_in_invoice(self.partner_ruc, auto_post=False)
        invoice.invoice_line_ids.tax_ids = [(5, 0)]
        self.assertFalse(invoice.invoice_line_ids.tax_ids)
        invoice.action_post()
        self.assertTrue(invoice.l10n_ec_withhold_active)
        invoice.action_try_create_ecuadorian_withhold()
        # Each wizard line answers with a "base amount for withholding is zero"
        # warning, because the invoice carries no taxes, and ``Form`` logs every
        # onchange warning it receives. Capture them so this expected path does
        # not surface as a run-time WARNING.
        with self.assertLogs("odoo.tests.form.onchange", level="WARNING"):
            wizard_form = self._prepare_new_wizard_withhold_purchase(
                invoice,
                tax_withhold_vat=self.tax_withhold_vat_100,
                tax_withhold_profit=self.tax_withhold_profit_303,
                tax_support_withhold_vat="01",
                tax_support_withhold_profit="01",
            )
        wizard = wizard_form.save()
        msj_expected = "The base amount for withholding is zero"
        with self.assertRaisesRegex(UserError, msj_expected):
            wizard.button_validate()

    @patch_service_sri
    def test_04_l10n_ec_withhold_two_invoices(self):
        # purchase withhold is only for one invoice
        self.partner_ruc.property_account_position_id = self.position_require_withhold
        invoice = self._l10n_ec_create_in_invoice(
            self.partner_ruc,
            auto_post=True,
            l10n_latam_document_number="001-001-000000001",
        )
        invoice2 = self._l10n_ec_create_in_invoice(
            self.partner_ruc,
            auto_post=True,
            l10n_latam_document_number="001-001-000000002",
        )
        self.assertTrue(invoice.l10n_ec_withhold_active)
        self.assertTrue(invoice2.l10n_ec_withhold_active)
        msj_expected = self.env._(
            "You can't create Withhold for some invoice, Please select only a Invoice."
        )
        with self.assertRaisesRegex(UserError, msj_expected):
            (invoice | invoice2).action_try_create_ecuadorian_withhold()

    @patch_service_sri
    def test_05_l10n_ec_new_electronic_withhold(self):
        self._setup_edi_company_ec()
        self.partner_ruc.property_account_position_id = self.position_require_withhold
        invoice_form = self._l10n_ec_create_form_move(
            move_type="in_invoice",
            internal_type="invoice",
            partner=self.partner_ruc,
            taxes=self.tax_vat,
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
        # 19.0 ``account.move.send`` is an AbstractModel; the concrete
        # single-move wizard is ``account.move.send.wizard``, and it picks the
        # move up from the ``active_model``/``active_ids`` context. Same shape
        # as ``l10n_ec_account_edi``'s ``l10n_ec_send_email``.
        #
        # ``action_invoice_sent()`` also injects
        # ``allow_partners_without_mail`` into the action context. Forwarding
        # it keeps the email-less partner in the wizard's ``mail_partner_ids``,
        # and ``_raise_danger_alerts`` then refuses to send. 17.0 could pass the
        # whole context because the wizard had no alert step. Only the template
        # is needed here, so forward only that.
        send_wizard = (
            self.env["account.move.send.wizard"]
            .with_context(
                active_model="account.move",
                active_ids=withhold.ids,
                default_template_id=report_action["context"]["default_template_id"],
            )
            .create({})
        )
        send_wizard.action_send_and_print()
        self.assertTrue(withhold.is_move_sent)
        # show withholding related
        action_withhold = invoice.action_show_l10n_ec_withholds()
        self.assertEqual(action_withhold["res_id"], withhold.id)

    @patch_service_sri
    def test_06_l10n_ec_check_withhold_values(self):
        """
        Pin the withheld amounts, per tax support.

        The invoice carries a single ``product_a`` line. Since 19.0
        ``account.move.line._compute_price_unit`` is a stored compute that takes
        ``standard_price`` (800.00) for purchase documents, taxed with
        ``tax_vat_510_sup_01`` (12%): ``price_subtotal`` 800.00, VAT 96.00,
        total 896.00. The wizard derives its bases from the invoice lines
        themselves: ``withhold_vat_purchase`` bases on
        ``price_total - price_subtotal`` (96.00) and
        ``withhold_income_purchase`` on ``price_subtotal`` (800.00). With 100%
        VAT withholding and 10% profit withholding the basis lines carry 96.00
        and 80.00 of ``l10n_ec_withhold_tax_amount``, and 176.00 leaves the
        invoice.
        """
        self._setup_edi_company_ec()
        self.partner_ruc.property_account_position_id = self.position_require_withhold
        invoice_form = self._l10n_ec_create_form_move(
            move_type="in_invoice",
            internal_type="invoice",
            partner=self.partner_ruc,
            taxes=self.tax_vat,
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
        self.assertEqual(invoice.amount_untaxed, 800.0)
        self.assertEqual(invoice.amount_tax, 96.0)
        self.assertEqual(invoice.amount_total, 896.0)
        self.assertTrue(invoice.l10n_ec_withhold_active)
        wizard_form = self._prepare_new_wizard_withhold_purchase(
            invoice,
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
        basis_lines = withhold.line_ids.filtered(
            lambda line: line.display_type == "product"
            and line.l10n_ec_invoice_withhold_id == invoice
            and line.tax_ids
        )
        self.assertEqual(len(basis_lines), 2)
        vat_basis = basis_lines.filtered(
            lambda line: line.tax_ids == self.tax_withhold_vat_100
        )
        profit_basis = basis_lines.filtered(
            lambda line: line.tax_ids == self.tax_withhold_profit_303
        )
        self.assertEqual(len(vat_basis), 1)
        self.assertEqual(len(profit_basis), 1)
        # 100% of the invoice VAT and 10% of its untaxed amount.
        self.assertEqual(vat_basis.l10n_ec_withhold_tax_amount, 96.0)
        self.assertEqual(profit_basis.l10n_ec_withhold_tax_amount, 80.0)
        self.assertEqual(vat_basis.l10n_ec_tax_support, "01")
        self.assertEqual(profit_basis.l10n_ec_tax_support, "01")
        # The same two amounts have to reach SRI in the ``retenciones`` block,
        # which is built from the withhold's own basis lines.
        edi_doc = withhold._get_edi_document(self.edi_format)
        retenciones = edi_doc._l10n_ec_get_support_data()[0]["retenciones"]
        retenciones_by_group = {vals["codigo"]: vals for vals in retenciones}
        self.assertEqual(len(retenciones_by_group), 2)
        vat_retencion = retenciones_by_group[
            self.tax_withhold_vat_100.tax_group_id.l10n_ec_xml_fe_code
        ]
        profit_retencion = retenciones_by_group[
            self.tax_withhold_profit_303.tax_group_id.l10n_ec_xml_fe_code
        ]
        self.assertEqual(float(vat_retencion["valor"]), 96.0)
        self.assertEqual(float(vat_retencion["baseImponible"]), 96.0)
        self.assertEqual(float(vat_retencion["tarifa"]), 100.0)
        self.assertEqual(float(profit_retencion["valor"]), 80.0)
        self.assertEqual(float(profit_retencion["baseImponible"]), 800.0)
        self.assertEqual(float(profit_retencion["tarifa"]), 10.0)
        # 176.00 withheld leaves 720.00 payable.
        self.assertEqual(invoice.amount_residual, 720.0)

    @patch_service_sri
    def test_07_l10n_ec_withhold_tax_lines_split_per_tax_support(self):
        """
        One withholding tax, two invoices under different tax supports.

        This is the case ``account.tax._prepare_base_line_grouping_key`` is
        overridden for: both basis lines carry the same withholding tax, so
        without the withholding dimensions in the accounting grouping key the
        two of them would share a single generated tax line. 17.0 split them
        through ``account.move.line.tax_key``, which no longer exists.
        """
        self._setup_edi_company_ec()
        self.partner_ruc.property_account_position_id = self.position_require_withhold
        invoice1 = self._l10n_ec_create_in_invoice(
            self.partner_ruc,
            taxes=self.tax_vat,
            auto_post=True,
            l10n_latam_document_number="001-001-000000001",
        )
        invoice1.l10n_ec_tax_support = "01"
        invoice2 = self._l10n_ec_create_in_invoice(
            self.partner_ruc,
            taxes=self.tax_vat,
            auto_post=True,
            l10n_latam_document_number="001-001-000000002",
        )
        invoice2.l10n_ec_tax_support = "03"
        invoices = invoice1 + invoice2
        wizard_form = self._prepare_new_wizard_withhold_purchase(
            invoices,
            tax_withhold_vat=self.tax_withhold_vat_100,
            tax_support_withhold_vat="01",
        )
        with wizard_form.withhold_line_ids.new() as line:
            line.invoice_id = invoice2
            line.tax_group_withhold_id = self.tax_withhold_vat_100.tax_group_id
            line.tax_withhold_id = self.tax_withhold_vat_100
            line.l10n_ec_tax_support = "03"
        withhold = wizard_form.save()
        withhold.button_validate()
        # Not asserted here: ``_try_reconcile_withholding_moves()`` takes a
        # single invoice but ``button_validate()`` hands it the whole set of
        # invoices, so a withholding over several invoices reconciles nothing.
        # That is pre-existing behaviour, identical in 17.0, and out of scope
        # for this migration; what matters here is the tax line grouping.
        withheld_moves = invoices.l10n_ec_withhold_ids
        self.assertEqual(len(withheld_moves), 1)
        withheld_move = withheld_moves[0]
        basis_lines = withheld_move.line_ids.filtered(
            lambda line: line.display_type == "product"
            and line.l10n_ec_invoice_withhold_id
            and line.tax_ids
        )
        self.assertEqual(len(basis_lines), 2)
        self.assertEqual(
            {line.l10n_ec_tax_support for line in basis_lines}, {"01", "03"}
        )
        self.assertEqual(
            {line.l10n_ec_invoice_withhold_id.id for line in basis_lines},
            set(invoices.ids),
        )
        self.assertEqual(
            {line.l10n_ec_withhold_tax_amount for line in basis_lines}, {96.0}
        )
        # One generated tax line per (invoice, tax support), not one for both.
        tax_lines = withheld_move.line_ids.filtered("tax_repartition_line_id")
        self.assertEqual(len(tax_lines), 2)
        tax_amount_by_support = {
            line.l10n_ec_tax_support: abs(line.balance) for line in tax_lines
        }
        self.assertEqual(tax_amount_by_support, {"01": 96.0, "03": 96.0})
        # Splitting must not move any money: the tax lines still add up to the
        # VAT of both invoices.
        self.assertEqual(
            sum(abs(line.balance) for line in tax_lines),
            invoice1.amount_tax + invoice2.amount_tax,
        )
        # And the withheld amounts still add up to what the invoices owed.
        self.assertEqual(
            sum(line.l10n_ec_withhold_tax_amount for line in basis_lines),
            invoice1.amount_tax + invoice2.amount_tax,
        )

    @patch_service_sri
    def test_08_l10n_ec_cancel_electronic_withhold(self):
        def mock_l10n_ec_edi_send_xml_with_auth(edi_doc_instance, client_ws):
            return self._get_response_with_auth(edi_doc_instance)

        def mock_l10n_ec_edi_process_response_auth_cancelled(instance, response):
            is_auth = False
            msj_list = []
            return is_auth, msj_list

        self._setup_edi_company_ec()
        self.partner_ruc.property_account_position_id = self.position_require_withhold
        invoice_form = self._l10n_ec_create_form_move(
            move_type="in_invoice",
            internal_type="invoice",
            partner=self.partner_ruc,
            taxes=self.tax_vat,
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
        # Cancel withhold
        with patch.object(
            AccountEdiDocument,
            "_l10n_ec_edi_process_response_auth",
            mock_l10n_ec_edi_process_response_auth_cancelled,
        ):
            withhold.button_cancel_posted_moves()
        self.assertEqual(edi_doc.state, "to_cancel")
        edi_doc._cron_process_documents_web_services()
        self.assertEqual(withhold.state, "cancel")
        self.assertFalse(withhold.show_reset_to_draft_button)
        msj_expected = "You can't unlink this Withhold was authorized on SRI."
        with self.assertRaisesRegex(UserError, msj_expected):
            withhold.unlink()
