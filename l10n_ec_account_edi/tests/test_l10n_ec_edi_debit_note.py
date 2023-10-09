import logging
from datetime import timedelta

from odoo.exceptions import UserError
from odoo.tests import Form, tagged

from .sri_response import patch_service_sri, validation_sri_response_returned
from .test_edi_common import TestL10nECEdiCommon

_logger = logging.getLogger(__name__)


FORM_ID = "account.view_move_form"


@tagged("post_install_l10n", "post_install", "-at_install")
class TestL10nClDte(TestL10nECEdiCommon):
    def test_l10n_ec_debit_note_configuration(self):
        # intentar validar una debit_note sin tener configurado correctamente los datos
        debit_note = self._l10n_ec_prepare_edi_debit_note()
        with self.assertRaises(UserError):
            debit_note.action_post()

    def _l10n_ec_prepare_edi_debit_note(
        self,
        partner=None,
        taxes=None,
        products=None,
        journal=None,
        latam_document_type=None,
        use_payment_term=False,
        auto_post=False,
    ):
        """Crea y devuelve una debit note electronica
        :param partner: Partner, si no se envia se coloca uno
        :param taxes: Impuestos, si no se envia se coloca impuestos del producto
        :param products: Productos, si no se envia se coloca uno
        :param journal: Diario, si no se envia se coloca
        por defecto diario para factura de venta
        :param latam_document_type: Tipo de documento, si no se envia se coloca uno
        :param use_payment_term: Si es True se coloca
        un término de pago a la liquidacion de compra, por defecto True
        :param auto_post: Si es True valida la factura
        y la devuelve en estado posted, por defecto False
        """
        partner = partner or self.partner_dni
        latam_document_type = latam_document_type or self.env.ref("l10n_ec.ec_dt_05")

        form = self._l10n_ec_create_form_move(
            move_type="out_invoice",
            internal_type="debit_note",
            partner=partner,
            taxes=taxes,
            products=products,
            journal=journal,
            latam_document_type=latam_document_type,
            use_payment_term=use_payment_term,
            form_id=FORM_ID,
        )
        form.l10n_ec_legacy_document_number = self.get_sequence_number()
        form.l10n_ec_legacy_document_date = self.current_datetime
        form.l10n_ec_legacy_document_authorization = (
            self.number_authorization_electronic
        )
        form.l10n_ec_reason = "Test debit note"
        debit_note = form.save()
        if auto_post:
            debit_note.action_post()
        return debit_note

    @patch_service_sri(validation_response=validation_sri_response_returned)
    def test_l10n_ec_debit_note_wrong_certificate(self):
        """Test para firmar una debit note con un certificado inválido"""
        self._setup_edi_company_ec()
        # Cambiar la contraseña del certificado de firma electrónica
        self.certificate.password = "invalid"
        debit_note = self._l10n_ec_prepare_edi_debit_note(auto_post=True)
        self.assertEqual("posted", debit_note.state)
        edi_doc = debit_note._get_edi_document(self.edi_format)

        with self.assertLogs(
            "odoo.addons.l10n_ec_account_edi.models.account_edi_format",
            level=logging.ERROR,
        ):
            edi_doc._process_documents_web_services(with_commit=False)

        self.assertFalse(edi_doc.edi_content)
        self.assertTrue(edi_doc.error)

    @patch_service_sri
    def test_l10n_ec_debit_note_sri(self):
        """Crear debit note electrónica, con la configuración correcta"""
        # Configurar los datos previamente
        self._setup_edi_company_ec()
        # Compañia no obligada a llevar contabilidad
        self._l10n_ec_edi_company_no_account()
        debit_note = self._l10n_ec_prepare_edi_debit_note(
            use_payment_term=False, auto_post=True
        )
        # TODO preguntar grupo odoo Ecuador migracion
        # self.generate_payment(invoice_ids=invoice.ids, journal=self.journal_cash)
        # self.assertEqual(invoice.payment_state, "paid")
        edi_doc = debit_note._get_edi_document(self.edi_format)
        edi_doc._process_documents_web_services(with_commit=False)
        self.assertEqual(debit_note.state, "posted")
        self.assertTrue(edi_doc.l10n_ec_xml_access_key)
        self.assertEqual(
            debit_note.l10n_ec_xml_access_key, edi_doc.l10n_ec_xml_access_key
        )
        self.assertEqual(edi_doc.state, "sent")
        self.assertEqual(
            debit_note.l10n_ec_authorization_date, edi_doc.l10n_ec_authorization_date
        )
        # Envio de email
        try:
            debit_note.action_invoice_sent()
            mail_sended = True
        except UserError as e:
            _logger.warning(e.name)
            mail_sended = False
        self.assertTrue(mail_sended)
        # TODO: validar que se autorice en el SRI con una firma válida

    @patch_service_sri(validation_response=validation_sri_response_returned)
    def test_l10n_ec_debit_note_back_sri(self):
        # Crear debit note con una fecha superior a la actual
        # para que el sri me la devuelva y no se autoriza
        self._setup_edi_company_ec()
        debit_note = self._l10n_ec_prepare_edi_debit_note()
        debit_note.invoice_date += timedelta(days=10)
        debit_note.action_post()
        edi_doc = debit_note._get_edi_document(self.edi_format)
        # Asignar el archivo xml básico para que lo encuentre y lo actualice
        edi_doc.attachment_id = self.attachment.id
        edi_doc._process_documents_web_services(with_commit=False)
        self.assertEqual(debit_note.state, "posted")
        self.assertTrue(edi_doc.l10n_ec_xml_access_key)
        self.assertIn("ERROR [65] FECHA EMISIÓN EXTEMPORANEA", edi_doc.error)
        self.assertEqual(edi_doc.blocking_level, "error")

    def test_l10n_ec_debit_note_default_values_form(self):
        """Test prueba campos computados y valores por defecto
        en formulario de debit note"""
        self._setup_edi_company_ec()
        journal = self.journal_sale.copy({"name": "liquidation Journal"})
        self.assertTrue(self.AccountMove._fields["l10n_latam_internal_type"].store)
        form = self._l10n_ec_create_form_move(
            move_type="out_invoice",
            internal_type="debit_note",
            partner=self.partner_dni,
            form_id=FORM_ID,
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
        self.assertEqual(form.l10n_latam_document_type_id.internal_type, "debit_note")
        for document in form.l10n_latam_available_document_type_ids[:]:
            self.assertEqual(document.internal_type, "debit_note")
        form.l10n_ec_legacy_document_number = self.get_sequence_number()
        form.l10n_ec_legacy_document_date = self.current_datetime
        form.l10n_ec_legacy_document_authorization = (
            self.number_authorization_electronic
        )
        form.l10n_ec_reason = "Test debit note"
        debit_note = form.save()
        self.assertTrue(debit_note.l10n_latam_internal_type, "debit_note")

    def test_l10n_ec_debit_note_default_journal_form(self):
        """Test prueba en formulario de debit note, sin diarios registrados"""
        self.journal_sale.unlink()
        debit_note_model = self.AccountMove.with_context(
            default_move_type="out_refund", internal_type="debit_note"
        )
        with self.assertRaises(UserError):
            Form(debit_note_model)

    def test_l10n_ec_validate_lines_debit_note(self):
        """Validaciones de cantidad y valor total en 0 en lineas de debit note"""
        self._setup_edi_company_ec()
        debit_note = self._l10n_ec_prepare_edi_debit_note()
        with Form(debit_note, FORM_ID) as form:
            with form.invoice_line_ids.edit(0) as line:
                line.quantity = 0
        with self.assertRaises(UserError):
            debit_note.action_post()
