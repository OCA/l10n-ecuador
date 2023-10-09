import logging
from datetime import timedelta
from unittest.mock import patch

from odoo import _
from odoo.exceptions import UserError
from odoo.tests import Form, tagged

from odoo.addons.l10n_ec_account_edi.models.account_edi_document import (
    AccountEdiDocument,
)

from .sri_response import patch_service_sri, validation_sri_response_returned
from .test_edi_common import TestL10nECEdiCommon

_logger = logging.getLogger(__name__)


@tagged("post_install_l10n", "post_install", "-at_install")
class TestL10nClDte(TestL10nECEdiCommon):
    def test_l10n_ec_out_invoice_configuration(self):
        # intentar validar una factura sin tener configurado correctamente los datos
        invoice = self._l10n_ec_prepare_edi_out_invoice()
        with self.assertRaises(UserError):
            invoice.action_post()

    @patch_service_sri(validation_response=validation_sri_response_returned)
    def test_l10n_ec_out_invoice_wrong_certificate(self):
        """Test para firmar una factura con un certificado inválido"""
        self._setup_edi_company_ec()
        # Cambiar la contraseña del certificado de firma electrónica
        self.certificate.password = "invalid"
        invoice = self._l10n_ec_prepare_edi_out_invoice(auto_post=True)
        self.assertEqual("posted", invoice.state)
        edi_doc = invoice._get_edi_document(self.edi_format)
        with self.assertLogs(
            "odoo.addons.l10n_ec_account_edi.models.account_edi_format",
            level=logging.ERROR,
        ):
            edi_doc._process_documents_web_services(with_commit=False)
        self.assertFalse(edi_doc.edi_content)
        self.assertTrue(edi_doc.error)

    @patch_service_sri
    def test_l10n_ec_out_invoice_sri(self):
        """Crear factura electrónica, con la configuración correcta"""
        # Configurar los datos previamente
        self._setup_edi_company_ec()
        # Compañia no obligada a llevar contabilidad
        self._l10n_ec_edi_company_no_account()
        invoice = self._l10n_ec_prepare_edi_out_invoice(
            use_payment_term=False, auto_post=True
        )
        # Añadir pago total a la factura
        self.generate_payment(invoice_ids=invoice.ids, journal=self.journal_cash)
        self.assertEqual(invoice.payment_state, "paid")
        edi_doc = invoice._get_edi_document(self.edi_format)
        edi_doc._process_documents_web_services(with_commit=False)
        self.assertEqual(invoice.state, "posted")
        self.assertTrue(edi_doc.l10n_ec_xml_access_key)
        self.assertEqual(invoice.l10n_ec_xml_access_key, edi_doc.l10n_ec_xml_access_key)
        self.assertEqual(edi_doc.state, "sent")
        self.assertEqual(
            invoice.l10n_ec_authorization_date, edi_doc.l10n_ec_authorization_date
        )
        # Envio de email
        try:
            invoice.action_invoice_sent()
            mail_sended = True
        except UserError as e:
            _logger.warning(e.name)
            mail_sended = False
        self.assertTrue(mail_sended)
        # TODO: validar que se autorice en el SRI con una firma válida

    @patch_service_sri
    def test_l10n_ec_out_invoice_sri_without_response(self):
        """
        Crear factura electrónica, simular no respuesta del SRI,
        intentar enviar nuevamente y ahi si autorizar
        """

        def mock_l10n_ec_edi_send_xml_with_auth(edi_doc_instance, client_ws):
            return self._get_response_with_auth(edi_doc_instance)

        def mock_l10n_ec_edi_send_xml_without_auth(edi_doc_instance, client_ws):
            return self._get_response_without_auth(edi_doc_instance)

        # Configurar los datos previamente
        self._setup_edi_company_ec()
        invoice = self._l10n_ec_prepare_edi_out_invoice(
            use_payment_term=False, auto_post=True
        )
        edi_doc = invoice._get_edi_document(self.edi_format)
        # simular respuesta del SRI donde no se tenga autorizaciones
        with patch.object(
            AccountEdiDocument,
            "_l10n_ec_edi_send_xml_auth",
            mock_l10n_ec_edi_send_xml_without_auth,
        ):
            edi_doc._process_documents_web_services(with_commit=False)
        # comprobar que la factura este validada,
        # pero documento edi se quede en estado to_send
        self.assertEqual(invoice.state, "posted")
        self.assertEqual(edi_doc.state, "to_send")
        self.assertTrue(edi_doc.l10n_ec_xml_access_key)
        # intentar enviar nuevamente al SRI,
        # como ya hubo un intento previo,
        # debe consultar el documento antes de volver a enviarlo
        with patch.object(
            AccountEdiDocument,
            "_l10n_ec_edi_send_xml_auth",
            mock_l10n_ec_edi_send_xml_with_auth,
        ):
            edi_doc._process_documents_web_services(with_commit=False)
        self.assertEqual(edi_doc.state, "sent")
        self.assertEqual(invoice.l10n_ec_xml_access_key, edi_doc.l10n_ec_xml_access_key)
        self.assertEqual(
            invoice.l10n_ec_authorization_date, edi_doc.l10n_ec_authorization_date
        )

    @patch_service_sri(validation_response=validation_sri_response_returned)
    def test_l10n_ec_out_invoice_back_sri(self):
        # Crear factura con una fecha superior a la actual
        # para que el sri me la devuelva y no se autoriza
        self._setup_edi_company_ec()
        invoice = self._l10n_ec_prepare_edi_out_invoice()
        invoice.invoice_date += timedelta(days=10)
        invoice.action_post()
        edi_doc = invoice._get_edi_document(self.edi_format)
        # Asignar el archivo xml básico para que lo encuentre y lo actualice
        edi_doc.attachment_id = self.attachment.id
        edi_doc._process_documents_web_services(with_commit=False)
        self.assertEqual(invoice.state, "posted")
        self.assertTrue(edi_doc.l10n_ec_xml_access_key)
        self.assertIn("ERROR [65] FECHA EMISIÓN EXTEMPORANEA", edi_doc.error)
        self.assertEqual(edi_doc.blocking_level, "error")

    def test_l10n_ec_out_invoice_with_foreign_client(self):
        # Factura con cliente sin identificación para que no se valide el XML
        self._setup_edi_company_ec()
        invoice = self._l10n_ec_prepare_edi_out_invoice(
            partner=self.partner_passport, auto_post=True
        )
        edi_doc = invoice._get_edi_document(self.edi_format)
        # Error en el archivo xml
        with self.assertLogs(
            "odoo.addons.l10n_ec_account_edi.models.account_edi_format",
            level=logging.ERROR,
        ):
            edi_doc._process_documents_web_services(with_commit=False)
        self.assertIn(_("EDI Error creating xml file"), edi_doc.error)
        # Enviar contexto para presentar clave de acceso de xml erroneo
        invoice.button_draft()
        invoice.action_post()
        edi_doc = invoice._get_edi_document(self.edi_format)
        with self.assertLogs(
            "odoo.addons.l10n_ec_account_edi.models.account_edi_document",
            level=logging.ERROR,
        ):
            edi_doc.with_context(
                l10n_ec_xml_call_from_cron=True
            )._process_documents_web_services(with_commit=False)
            self.assertIn(_("ARCHIVO NO CUMPLE ESTRUCTURA XML"), edi_doc.error)

    @patch_service_sri
    def test_l10n_ec_out_invoice_with_payments(self):
        """Crear factura electronica con 2 pagos"""
        self._setup_edi_company_ec()
        invoice = self._l10n_ec_prepare_edi_out_invoice(auto_post=True)
        # 2 Pagos para el total de la factura
        amount = invoice.amount_total / 2
        # Pago con diario efectivo
        self.generate_payment(
            invoice_ids=invoice.ids, journal=self.journal_cash, amount=amount
        )
        # Pago con diario banco por defecto
        self.generate_payment(invoice_ids=invoice.ids, amount=amount)
        edi_doc = invoice._get_edi_document(self.edi_format)
        edi_doc._process_documents_web_services(with_commit=False)
        self.assertEqual(invoice.state, "posted")
        self.assertEqual(invoice.payment_state, "paid")
        self.assertTrue(edi_doc.l10n_ec_xml_access_key)

    def test_l10n_ec_out_invoice_default_values_form(self):
        """Test prueba campos computados y valores por defecto
        en formulario de Factura de cliente"""
        self._setup_edi_company_ec()
        journal = self.journal_sale.copy({"name": "Invoices Journal"})
        self.assertTrue(self.AccountMove._fields["l10n_latam_internal_type"].store)
        form = self._l10n_ec_create_form_move(
            move_type="out_invoice", internal_type="invoice", partner=self.partner_cf
        )
        self.assertIn(form.journal_id, journal + self.journal_sale)
        self.assertRecordValues(
            form.journal_id,
            [
                {
                    "type": "sale",
                    "l10n_latam_use_documents": True,
                }
            ],
        )
        self.assertEqual(form.invoice_filter_type_domain, "sale")
        self.assertEqual(journal + self.journal_sale, form.suitable_journal_ids[:])
        for journal in form.suitable_journal_ids[:]:
            self.assertRecordValues(
                journal,
                [
                    {
                        "type": "sale",
                        "l10n_latam_use_documents": True,
                    }
                ],
            )
        self.assertEqual(form.l10n_latam_document_type_id.internal_type, "invoice")
        for document in form.l10n_latam_available_document_type_ids[:]:
            self.assertEqual(document.internal_type, "invoice")
        invoice = form.save()
        self.assertTrue(invoice.l10n_latam_internal_type, "invoice")

    def test_l10n_ec_out_invoice_default_journal_form(self):
        """Test prueba en formulario de factura, sin diarios registrados"""
        self.journal_sale.unlink()
        invoice_model = self.AccountMove.with_context(
            default_move_type="out_invoice", internal_type="invoice"
        )
        with self.assertRaises(UserError):
            Form(invoice_model)

    def test_l10n_ec_out_invoice_final_consumer_limit_amount(self):
        """Test prueba monto maximo en Factura de cliente
        emitida a consumidor final"""
        self._setup_edi_company_ec()
        self.env["ir.config_parameter"].sudo().set_param(
            "l10n_ec_final_consumer_limit", 50
        )
        self.product_a.list_price = 51
        form = self._l10n_ec_create_form_move(
            move_type="out_invoice",
            internal_type="invoice",
            partner=self.env.ref("l10n_ec.ec_final_consumer"),
        )
        invoice = form.save()
        with self.assertRaises(UserError):
            invoice.action_post()
        self.product_a.list_price = 40
        form = self._l10n_ec_create_form_move(
            move_type="out_invoice",
            internal_type="invoice",
            partner=self.env.ref("l10n_ec.ec_final_consumer"),
        )
        invoice = form.save()
        invoice.action_post()
        self.assertEqual(invoice.state, "posted")

    def test_l10n_ec_validate_lines_invoice(self):
        """Validaciones de cantidad y valor total en 0 en lineas de facturas"""
        self._setup_edi_company_ec()
        invoice = self._l10n_ec_prepare_edi_out_invoice()
        with Form(invoice) as form:
            with form.invoice_line_ids.edit(0) as line:
                line.quantity = 0
        with self.assertRaises(UserError):
            invoice.action_post()

    @patch_service_sri
    def test_l10n_ec_out_invoice_with_additional_info(self):
        """Crear factura electronica con informacion adicional"""
        self._setup_edi_company_ec()
        invoice = self._l10n_ec_prepare_edi_out_invoice(auto_post=False)
        with Form(invoice) as form:
            with form.l10n_ec_additional_information_move_ids.new() as line:
                line.name = "Test"
                line.description = "ABC"
        invoice.action_post()
        edi_doc = invoice._get_edi_document(self.edi_format)
        edi_doc._process_documents_web_services(with_commit=False)
        self.assertEqual(invoice.state, "posted")
        self.assertTrue(edi_doc.l10n_ec_xml_access_key)
        self.assertEqual(len(invoice.l10n_ec_additional_information_move_ids), 1)
        self.assertEqual(
            invoice.l10n_ec_additional_information_move_ids[0].name, "Test"
        )
