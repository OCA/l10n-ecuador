import base64
import xml.etree.ElementTree as ET

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import Form

from odoo.addons.l10n_ec_account_edi.tests.sri_response import patch_service_sri
from odoo.addons.l10n_ec_withhold.tests.test_l10n_ec_purchase_withhold import (
    TestL10nPurchaseWithhold,
)

FORM_ID = "l10n_ec_account_edi.account_invoice_liquidation_purchase_form_view"


def sri_get_name(date):
    date_end = date.replace(day=1) + relativedelta(months=1, days=-1)
    return "AT%s" % (date_end.strftime("%Y%m"))


@tagged("post_install_l10n", "post_install", "-at_install")
class TestL10nSriAts(TestL10nPurchaseWithhold):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
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

        WizardWithhold = self.env["l10n_ec.wizard.create.sale.withhold"]
        wizard = Form(WizardWithhold.with_context(active_ids=invoices.ids))
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

    def _prepare_invoice_with_purchase_withhold(self, invoice=None):
        if invoice is None:
            invoice = self._l10n_ec_create_in_invoice(self.partner_ruc, auto_post=True)
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

    def _l10n_ec_prepare_edi_liquidation(
        self,
        partner=None,
        taxes=None,
        products=None,
        journal=None,
        latam_document_type=None,
        use_payment_term=True,
        auto_post=False,
    ):
        """Crea y devuelve una liquidacion de compra electronica
        :param partner: Partner, si no se envia se coloca uno
        :param taxes: Impuestos, si no se envia se coloca impuestos del producto
        :param products: Productos, si no se envia se coloca uno
        :param journal: Diario, si no se envia se coloca
        por defecto diario para factura de compra
        :param latam_document_type: Tipo de documento, si no se envia se coloca uno
        :param use_payment_term: Si es True se coloca
        un término de pago a la liquidacion de compra, por defecto True
        :param auto_post: Si es True valida la factura
        y la devuelve en estado posted, por defecto False
        """
        partner = partner or self.partner_dni
        latam_document_type = latam_document_type or self.env.ref("l10n_ec.ec_dt_03")
        form = self._l10n_ec_create_form_move(
            move_type="in_invoice",
            internal_type="purchase_liquidation",
            partner=partner,
            taxes=taxes,
            products=products,
            journal=journal,
            latam_document_type=latam_document_type,
            use_payment_term=use_payment_term,
            form_id=FORM_ID,
        )
        invoice = form.save()
        if auto_post:
            invoice.action_post()
        return invoice

    def _prepare_invoice_with_sale_withhold(
        self, invoice=False, new_document_number=False, electronic_authorization=False
    ):
        if not invoice:
            invoice = self.get_invoice(self.partner_ruc)
        if not new_document_number:
            new_document_number = "1-1-4"
        if not electronic_authorization:
            electronic_authorization = "1234567890"
        wizard = self._prepare_new_wizard_withhold(
            invoice,
            new_document_number=new_document_number,
            electronic_authorization=electronic_authorization,
            tax_withhold_vat=self.tax_sale_withhold_vat_100,
            tax_withhold_profit=self.tax_sale_withhold_profit_303,
        )
        wizard = wizard.save()
        wizard.button_validate()
        return invoice

    def _create_data_for_ats(self):
        self.partner_ruc.property_account_position_id = self.position_require_withhold
        self._setup_edi_company_ec()
        invoices = self.get_invoice(self.partner_dni)
        out_invoice = self._prepare_invoice_with_sale_withhold()
        out_invoice |= self._prepare_invoice_with_sale_withhold(
            invoice=invoices,
            new_document_number="1-1-5",
            electronic_authorization="1111111111",
        )
        invoice = self._prepare_invoice_with_purchase_withhold()
        liquidation = self._l10n_ec_prepare_edi_liquidation(
            auto_post=True, partner=self.partner_ruc
        )
        liquidation = self._prepare_invoice_with_purchase_withhold(liquidation)
        in_invoices = invoice | liquidation

        return {"out_invoice": out_invoice, "in_invoice": in_invoices}

    def xml_to_dict(self, xml_file):
        decoded_xml = base64.b64decode(xml_file).decode("utf-8")
        root = ET.fromstring(decoded_xml)
        data_dict = {"compras": [], "ventas": []}

        for compra in root.findall(".//compras/detalleCompras"):
            compra_data = {
                "codSustento": compra.find("codSustento").text,
                "tpIdProv": compra.find("tpIdProv").text,
                "idProv": compra.find("idProv").text,
                "tipoComprobante": compra.find("tipoComprobante").text,
                "baseImpGrav": compra.find("baseImpGrav").text,
                "montoIva": compra.find("montoIva").text,
                "valRetServ100": compra.find("valRetServ100").text,
            }
            data_dict["compras"].append(compra_data)

        for venta in root.findall(".//ventas/detalleVentas"):
            venta_data = {
                "tpIdCliente": venta.find("tpIdCliente").text,
                "idCliente": venta.find("idCliente").text,
                "baseImpGrav": venta.find("baseImpGrav").text,
                "montoIva": venta.find("montoIva").text,
                "valorRetIva": venta.find("valorRetIva").text,
            }
            data_dict["ventas"].append(venta_data)

        return data_dict

    def sri_get_name(self, date):
        date_end = date.replace(day=1) + relativedelta(months=1, days=-1)
        return "AT%s" % (date_end.strftime("%Y%m"))

    def create_sri_report(self, date=False):
        sriats = self.env["sri.ats"].create({})
        if date:
            sriats.date_start = date.replace(day=1)
            sriats.date_end = sriats.date_start + relativedelta(months=1, days=-1)
        return sriats

    def test_create_ats_name(self):
        M_ATS = self.env["sri.ats"]
        current_date = fields.Date.context_today(M_ATS) - relativedelta(months=1)
        sriats = self.create_sri_report()
        self.assertEqual(sriats.name, sri_get_name(current_date))

    def test_create_ats_name_change_date(self):
        M_ATS = self.env["sri.ats"]
        current_date = fields.Date.context_today(M_ATS)
        sriats = self.create_sri_report(current_date)
        self.assertEqual(sriats.name, sri_get_name(current_date))

    def test_ats_action(self):
        M_ATS = self.env["sri.ats"]
        current_date = fields.Date.context_today(M_ATS)
        sriats = self.create_sri_report(current_date)
        self.assertTrue(sriats.sri_state == "draft")
        self.assertFalse(sriats.xml_file)
        sriats.action_load()
        self.assertTrue(sriats.xml_file)
        sriats.action_done()
        self.assertTrue(sriats.sri_state == "done")
        sriats.action_draft()
        self.assertTrue(sriats.sri_state == "draft")

    def test_ats_data(self):
        M_ATS = self.env["sri.ats"]
        data = self._create_data_for_ats()
        current_date = fields.Date.context_today(M_ATS)
        sriats = self.create_sri_report(current_date)
        sriats.action_load()
        xml_date = self.xml_to_dict(sriats.xml_file)
        compras = data["in_invoice"]
        ventas = data["out_invoice"]

        self.assertEqual(
            sum(compras.mapped("amount_untaxed")),
            sum([float(x["baseImpGrav"]) for x in xml_date["compras"]]),
        )
        self.assertEqual(
            sum(ventas.mapped("amount_untaxed")),
            sum([float(x["baseImpGrav"]) for x in xml_date["ventas"]]),
        )

        self.assertEqual(
            sum(compras.mapped("amount_tax")),
            sum([float(x["montoIva"]) for x in xml_date["compras"]]),
        )
        self.assertEqual(
            sum(ventas.mapped("amount_tax")),
            sum([float(x["montoIva"]) for x in xml_date["ventas"]]),
        )
