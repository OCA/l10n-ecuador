import logging
from datetime import timedelta

from odoo.exceptions import UserError
from odoo.tests import Form, tagged

from .sri_response import patch_service_sri, validation_sri_response_returned
from .test_edi_common import TestL10nECEdiCommon

_logger = logging.getLogger(__name__)

FORM_ID = "l10n_ec_account_edi.account_invoice_liquidation_purchase_form_view"


@tagged("post_install_l10n", "post_install", "-at_install")
class TestL10nEcPurchaseLiquidation(TestL10nECEdiCommon):
    def test_l10n_ec_liquidation_configuration(self):
        # Validar Liquidacion de compras sin tener configurado correctamente los datos
        invoice = self._l10n_ec_prepare_edi_liquidation()
        with self.assertRaises(UserError):
            invoice.action_post()
        self._setup_edi_company_ec()
        invoice = self._l10n_ec_prepare_edi_liquidation()
        invoice.company_id.l10n_ec_liquidation_version = False
        with self.assertRaisesRegex(
            UserError, "You must set XML Version for Purchase Liquidation into company"
        ):
            invoice.action_post()

    @patch_service_sri(validation_response=validation_sri_response_returned)
    def test_l10n_ec_liquidation_wrong_certificate(self):
        """Test para firmar una liquidación de compra con un certificado inválido"""
        self._setup_edi_company_ec()
        # Cambiar la contraseña del certificado de firma electrónica
        self.certificate.password = "invalid"
        invoice = self._l10n_ec_prepare_edi_liquidation(auto_post=True)
        self.assertEqual("posted", invoice.state)
        edi_doc = invoice._get_edi_document(self.edi_format)
        with self.assertLogs("odoo.addons.l10n_ec_account_edi"):
            edi_doc._process_documents_web_services(with_commit=False)
        self.assertFalse(edi_doc.edi_content)
        self.assertTrue(edi_doc.error)

    @patch_service_sri
    def test_l10n_ec_liquidation_sri(self):
        """Crear liquidación de compra electrónica, con la configuración correcta"""
        # Configurar los datos previamente
        self._setup_edi_company_ec()
        # Compañia no obligada a llevar contabilidad
        self._l10n_ec_edi_company_no_account()
        invoice = self._l10n_ec_prepare_edi_liquidation(
            use_payment_term=False, auto_post=True
        )
        # Añadir pago total a la liquidación de compra
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

    @patch_service_sri(validation_response=validation_sri_response_returned)
    def test_l10n_ec_liquidation_back_sri(self):
        # Crear liquidación de compra con una fecha superior a la actual
        # para que el sri me la devuelva y no se autoriza
        self._setup_edi_company_ec()
        invoice = self._l10n_ec_prepare_edi_liquidation()
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

    @patch_service_sri
    def test_l10n_ec_liquidation_with_foreign_client(self):
        # Liquidación de compras con cliente extrangero sin identificación
        self._setup_edi_company_ec()
        # Compañia no obligada a llevar contabilidad
        self._l10n_ec_edi_company_no_account()
        invoice = self._l10n_ec_prepare_edi_liquidation(
            partner=self.partner_passport, use_payment_term=False, auto_post=True
        )
        # Añadir pago total a la liquidación de compra
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

    @patch_service_sri
    def test_l10n_ec_liquidation_with_payments(self):
        """Crear liquidación de compras electrónica con 2 pagos"""
        self._setup_edi_company_ec()
        invoice = self._l10n_ec_prepare_edi_liquidation(auto_post=True)
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

    def test_l10n_ec_liquidation_default_values_form(self):
        """Test prueba campos computados y valores por defecto
        en formulario de liquidación de compras"""
        self._setup_edi_company_ec()
        journal = self.journal_purchase.copy({"name": "liquidation Journal"})
        self.assertTrue(self.AccountMove._fields["l10n_latam_internal_type"].store)
        form = self._l10n_ec_create_form_move(
            move_type="in_invoice",
            internal_type="purchase_liquidation",
            partner=self.partner_dni,
            form_id=FORM_ID,
        )
        self.assertIn(form.journal_id, journal + self.journal_purchase)
        self.assertRecordValues(
            form.journal_id,
            [
                {
                    "type": "purchase",
                    "l10n_latam_use_documents": True,
                    "l10n_ec_is_purchase_liquidation": True,
                }
            ],
        )
        self.assertEqual(form.invoice_filter_type_domain, "purchase")
        self.assertEqual(journal + self.journal_purchase, form.suitable_journal_ids[:])
        for journal in form.suitable_journal_ids[:]:
            self.assertRecordValues(
                journal,
                [
                    {
                        "type": "purchase",
                        "l10n_latam_use_documents": True,
                        "l10n_ec_is_purchase_liquidation": True,
                    }
                ],
            )
        self.assertEqual(
            form.l10n_latam_document_type_id.internal_type, "purchase_liquidation"
        )
        for document in form.l10n_latam_available_document_type_ids[:]:
            self.assertEqual(document.internal_type, "purchase_liquidation")
        invoice = form.save()
        self.assertTrue(invoice.l10n_latam_internal_type, "purchase_liquidation")

    def test_l10n_ec_liquidation_default_journal_form(self):
        """Test prueba en formulario de liquidación de compras, sin diarios
        registrados
        """
        self.journal_purchase.unlink()
        invoice_model = self.AccountMove.with_context(
            default_move_type="in_invoice", internal_type="purchase_liquidation"
        )
        with self.assertRaises(UserError):
            Form(invoice_model)

    def test_l10n_ec_validate_lines_liquidation(self):
        """Validaciones de cantidad y valor total en 0 en lineas de liquidación de
        compra
        """
        self._setup_edi_company_ec()
        invoice = self._l10n_ec_prepare_edi_liquidation()
        with Form(invoice, FORM_ID) as form:
            with form.invoice_line_ids.edit(0) as line:
                line.quantity = 0
        with self.assertRaises(UserError):
            invoice.action_post()

    @patch_service_sri
    def test_l10n_ec_liquidation_action_send_and_print(self):
        """Test action_send_and_print for purchase liquidation opens custom wizard"""
        self._setup_edi_company_ec()
        liquidation = self._l10n_ec_prepare_edi_liquidation(auto_post=True)
        edi_doc = liquidation._get_edi_document(self.edi_format)
        edi_doc._process_documents_web_services(with_commit=False)

        # Llamar a action_send_and_print para liquidación de compra
        result = liquidation.action_send_and_print()

        # Verificar que devuelve el wizard account.move.send
        self.assertEqual(result["type"], "ir.actions.act_window")
        self.assertEqual(result["res_model"], "account.move.send")
        self.assertEqual(result["view_mode"], "form")
        self.assertEqual(result["target"], "new")
        self.assertIn("context", result)
        self.assertIn("active_ids", result["context"])
        self.assertIn(liquidation.id, result["context"]["active_ids"])
        self.assertIn("default_mail_template_id", result["context"])
