from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.tests import tagged

from odoo.addons.l10n_ec_withhold.tests.test_l10n_ec_purchase_withhold import (
    TestL10nPurchaseWithhold,
)
from odoo.addons.l10n_ec_withhold.tests.test_l10n_ec_sale_withhold import (
    TestL10nSaleWithhold,
)


def sri_get_name(date):
    date_end = date.replace(day=1) + relativedelta(months=1, days=-1)
    return "AT%s" % (date_end.strftime("%Y%m"))


@tagged("post_install_l10n", "post_install", "-at_install")
class TestL10nSriAts(TestL10nSaleWithhold):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def _create_sale_invoice_and_withhold(self):
        self.product_a.list_price = 100
        partner = self.partner_with_email
        invoice1 = self.get_invoice(partner)
        invoice2 = self.get_invoice(partner)
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
        SRIATS = self.env["sri.ats"]
        current_date = fields.Date.context_today(SRIATS)
        self._create_sale_invoice_and_withhold()
        srists = self.create_sri_report(current_date)

        srists.action_load()
        srists.action_done()
        self.assertTrue(srists.sri_state == "done")
        srists.action_draft()
        self.assertTrue(srists.sri_state == "draft")
        data = srists._l10n_ec_get_info_ats()
        self.assertTrue(data["idInformante"] == self.company.partner_id.vat)
        self.assertTrue(data["anio"] == current_date.strftime("%Y"))
        self.assertTrue(data["mes"] == current_date.strftime("%m"))
        self.assertTrue((srists.name + ".xml") == srists.file_name)


class TestL10nSriAtsPurchase(TestL10nPurchaseWithhold):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def create_sri_report(self, date=False):
        srists = self.env["sri.ats"].create({})
        if date:
            srists.date_start = date.replace(day=1)
            srists.date_end = srists.date_start + relativedelta(months=1, days=-1)
        return srists

    def _create_purchase_invoice_and_withhold(self):
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

    def test_sri_data_purchase(self):
        SRIATS = self.env["sri.ats"]
        current_date = fields.Date.context_today(SRIATS)
        invoice = self._create_purchase_invoice_and_withhold()
        srists = self.create_sri_report(current_date)
        # srists.action_load()
        data = srists._l10n_ec_get_info_ats()
        self.assertTrue(data["exist_compras"])
        self.assertTrue(data["compras_detalles"])
        data_invoice = data["compras_detalles"][0]
        self.assertTrue(
            data_invoice["tpIdProv"]
            == invoice.partner_id.l10n_latam_identification_type_id.l10n_ec_code
        )
        self.assertTrue(data_invoice["idProv"] == invoice.partner_id.vat)
        self.assertTrue(
            data_invoice["tipoComprobante"] == invoice.l10n_latam_document_type_id.code
        )
        self.assertTrue(data_invoice["aut"] == invoice.l10n_ec_electronic_authorization)
        self.assertTrue(data_invoice["estab"] == invoice.l10n_latam_document_number[:3])
        self.assertTrue(
            data_invoice["ptoEmi"] == invoice.l10n_latam_document_number[4:7]
        )
        self.assertTrue(
            data_invoice["secuencial"] == invoice.l10n_latam_document_number[8:]
        )
        self.assertTrue(
            data_invoice["fechaEmision"] == invoice.invoice_date.strftime("%d/%m/%Y")
        )
        self.assertTrue(data_invoice["baseNoGraIva"] == 0)
        self.assertTrue(data_invoice["baseImponible"] == 100)
        self.assertTrue(data_invoice["baseImpGrav"] == 100)
        self.assertTrue(data_invoice["baseNoObjIva"] == 0)
        self.assertTrue(data_invoice["montoIva"] == 15)
        self.assertTrue(data_invoice["valorRetIva"] == 15)
