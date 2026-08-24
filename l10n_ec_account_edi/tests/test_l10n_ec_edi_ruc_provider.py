from lxml import etree

from odoo.tests import tagged

from .sri_response import patch_service_sri
from .test_edi_common import TestL10nECEdiCommon


@tagged("post_install_l10n", "post_install", "-at_install")
class TestL10nRucProvider(TestL10nECEdiCommon):
    @patch_service_sri
    def test_l10n_ec_ruc_provider_out_invoice(self):
        """Crear factura electrónica, con la configuración correcta"""
        # Configurar los datos previamente
        self._setup_edi_company_ec()
        invoice = self._l10n_ec_prepare_edi_out_invoice(
            use_payment_term=False, auto_post=True
        )
        edi_doc = invoice._get_edi_document(self.edi_format)
        xml_string = edi_doc._l10n_ec_render_xml_edi()
        xml_doc = etree.fromstring(xml_string)
        node_ruc_provider = xml_doc.xpath(
            "//infoAdicional/campoAdicional[@nombre='RUC Proveedor']"
        )
        self.assertEqual(len(node_ruc_provider), 0)
        # Establecer el RUC del proveedor en el parametro del sistema
        self.env["ir.config_parameter"].sudo().set_param(
            "l10n_ec_fe_ruc_provider", "1790012345001"
        )
        xml_string = edi_doc._l10n_ec_render_xml_edi()
        xml_doc = etree.fromstring(xml_string)
        node_ruc_provider = xml_doc.xpath(
            "//infoAdicional/campoAdicional[@nombre='RUC Proveedor']"
        )
        self.assertEqual(len(node_ruc_provider), 1)
        self.assertEqual(node_ruc_provider[0].text, "1790012345001")
        report = self.env.ref("account.account_invoices")
        res = str(
            report._render_qweb_html(
                "account.report_invoice_with_payments", invoice.ids
            )[0]
        )
        self.assertIn("RUC Proveedor", res)
        self.assertIn("1790012345001", res)
