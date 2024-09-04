from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.tests import tagged

from odoo.addons.l10n_ec_withhold.tests.test_l10n_ec_purchase_withhold import (
    TestL10nPurchaseWithhold,
)


def sri_get_name(date):
    date_end = date.replace(day=1) + relativedelta(months=1, days=-1)
    return "AT%s" % (date_end.strftime("%Y%m"))


@tagged("post_install_l10n", "post_install", "-at_install")
class TestL10nSriAts(TestL10nPurchaseWithhold):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def _create_invoice_and_withhold(self):
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
        return invoice

    def create_sri_report(self, date=False):
        srists = self.env["sri.ats"].create({})
        if date:
            srists.date_start = date.replace(day=1)
            srists.date_end = srists.date_start + relativedelta(months=1, days=-1)
        return srists

    def test_create_ats_name(self):
        SRIATS = self.env["sri.ats"]
        current_date = fields.Date.context_today(SRIATS) - relativedelta(months=1)
        srists = self.create_sri_report()
        self.assertEqual(srists.name, sri_get_name(current_date))

    def test_create_ats_name_change_date(self):
        SRIATS = self.env["sri.ats"]
        current_date = fields.Date.context_today(SRIATS)
        srists = self.create_sri_report(current_date)
        self.assertEqual(srists.name, sri_get_name(current_date))

    def test_sri_data_purchase(self):
        self._create_invoice_and_withhold()
        srists = self.create_sri_report()
        srists.action_load()
        self.assertTrue(srists.xml_file)
        self.assertTrue((srists.name + ".xml") == srists.file_name)
