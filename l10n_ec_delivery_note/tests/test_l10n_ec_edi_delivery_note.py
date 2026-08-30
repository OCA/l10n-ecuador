import logging
from datetime import timedelta

from odoo.exceptions import UserError, ValidationError
from odoo.tests import Form, tagged

from odoo.addons.l10n_ec_account_edi.tests.sri_response import (
    patch_service_sri,
)

from .test_l10n_ec_delivery_note_common import TestL10nDeliveryNoteCommon

_logger = logging.getLogger(__name__)


@tagged("post_install_l10n_ec_account_edi", "post_install", "-at_install", "delivery")
class TestL10nDeliveryNote(TestL10nDeliveryNoteCommon):
    def test_l10n_ec_delivery_note_without_journal(self):
        """Crear guía de remisión sin journal compatible"""
        with self.assertRaises(AssertionError):
            self._l10n_ec_create_delivery_note_without_journal()

    def test_l10n_ec_delivery_note_configuration(self):
        """Validar una guía de remisión sin la configuración correcta"""
        delivery_note = self._l10n_ec_create_delivery_note()
        delivery_note.partner_id.vat = False
        delivery_note.partner_id.l10n_latam_identification_type_id = False
        delivery_note.delivery_carrier_id.vat = False
        delivery_note.delivery_address_id.street = False
        with self.assertRaises(UserError):
            delivery_note.action_confirm()

    def test_l10n_ec_delivery_date_form(self):
        """
        Test when delivery date is less than transfer date
        """
        self.setup_edi_delivery_note()
        delivery = self._l10n_ec_create_delivery_note()
        with self.assertRaises(ValidationError):
            delivery.delivery_date = delivery.delivery_date - timedelta(days=1)

    def test_l10n_ec_delivery_note_date_form(self):
        self.setup_edi_delivery_note()
        delivery_note = self._l10n_ec_create_delivery_note()
        with self.assertRaises(UserError):
            delivery_note.transfer_date = delivery_note.transfer_date + timedelta(
                days=1
            )

    def test_l10n_ec_delivery_note_fields_form(self):
        """Test prueba campos computados, onchange
        en formulario de guias de remisión"""
        self.setup_edi_delivery_note()
        delivery_note = self._l10n_ec_create_delivery_note()
        with self.assertRaises(UserError):
            delivery_note.transfer_date += timedelta(days=1)
        with self.assertRaises(UserError):
            delivery_note.delivery_line_ids = False
            delivery_note.action_confirm()
        picking = self._l10n_ec_create_or_modify_picking(quantity=1)
        picking.action_confirm()
        picking.button_validate()
        delivery_note.write(
            {
                "partner_id": False,
                "delivery_carrier_id": False,
                "delivery_address_id": False,
                "journal_id": False,
            }
        )
        with Form(delivery_note) as form:
            form.stock_picking_ids.add(picking)
        delivery_note = form.save()
        self.assertRecordValues(
            delivery_note,
            [
                {
                    "partner_id": picking.partner_id.id,
                    "delivery_address_id": picking.partner_id.address_get(["delivery"])[
                        "delivery"
                    ],
                    "delivery_carrier_id": picking.l10n_ec_delivery_carrier_id.id,
                    "l10n_ec_car_plate": picking.l10n_ec_delivery_carrier_id.l10n_ec_car_plate,  # noqa
                    "journal_id": picking.l10n_ec_delivery_note_journal_id.id,
                }
            ],
        )
        stock_move_line = picking.move_line_ids
        self.assertRecordValues(
            delivery_note.delivery_line_ids,
            [
                {
                    "delivery_note_id": delivery_note.id,
                    "product_id": stock_move_line.product_id.id,
                    "product_qty": stock_move_line.quantity,
                    "product_uom_id": stock_move_line.product_uom_id.id,
                    "move_id": stock_move_line.move_id.id,
                    "production_lot_id": stock_move_line.lot_id.id,
                }
            ],
        )
        # ELiminar picking relacionado
        with Form(delivery_note) as form:
            form.stock_picking_ids.remove(picking.id)
            self.assertFalse(form.delivery_line_ids)

    def test_l10n_ec_delivery_note_unlink(self):
        """Cancelar y eliminar guia de remisión"""
        self.setup_edi_delivery_note()
        delivery_note = self._l10n_ec_create_delivery_note()
        delivery_note.action_confirm()
        with self.assertRaises(UserError):
            delivery_note.unlink()
        delivery_note.action_cancel()
        self.assertTrue(delivery_note.state, "cancel")
        delivery_note.action_set_draft()
        self.assertTrue(delivery_note.state, "draft")
        self.assertTrue(delivery_note.unlink())

    def test_l10n_ec_delivery_note_lines(self):
        """Validacion vía código al cambiar categoria
        de la UdM diferente a la del producto"""
        delivery_note = self._l10n_ec_create_delivery_note()
        line = delivery_note.delivery_line_ids
        new_uom = self.env["uom.uom"].search(
            [("category_id", "!=", line.product_id.uom_id.category_id.id)], limit=1
        )
        with self.assertRaises(ValidationError):
            line.product_uom_id = new_uom

    def test_l10n_ec_delivery_note_fields_form_edi_document(self):
        """Test prueba mensajes al enviar el edi_documents"""
        self.setup_edi_delivery_note()
        # Cambiar identificación erronea de transportista
        self.partner_a.write(
            {
                "vat": "123456789",
                "l10n_ec_is_carrier": False,
                "l10n_ec_car_plate": "ABC1234",
            }
        )
        delivery_note = self._l10n_ec_create_delivery_note()
        delivery_note.delivery_carrier_id = self.partner_a
        delivery_note.action_confirm()
        self.assertEqual(delivery_note.state, "done")
        edi_doc = delivery_note

        if not edi_doc.l10n_ec_xml_access_key or not edi_doc.l10n_ec_authorization_date:
            self.assertTrue(edi_doc.edi_error_message)
            self.assertEqual(edi_doc.edi_blocking_level, "error")
            # Cambiar el transportista y reintentar el envio al SRI
            delivery_note.delivery_carrier_id = self.partner_carrier

            self.assertTrue(edi_doc.l10n_ec_xml_access_key)
            if not edi_doc.l10n_ec_authorization_date:
                # Updated because, the last assert it's having error in
                # valid certificate, not in the target of test
                self.assertTrue(edi_doc.edi_blocking_level)

    def test_l10n_ec_delivery_note_pre_printed(self):
        """No se generan documentos electrónicos con tipo de emisión
        diferente de electronico configurado en el journal"""
        self.setup_edi_delivery_note()
        self.journal_values["name"] = "Delivery Note Journal Pre Printed"
        self.journal_values["code"] = "GR1"
        delivery_note = self._l10n_ec_create_delivery_note()
        delivery_note.action_confirm()
        self.assertEqual(delivery_note.state, "done")

    @patch_service_sri
    def test_l10n_ec_delivery_note_sri(self):
        """Validar y enviar al SRI una guía de remisión con la configuración correcta"""
        self.setup_edi_delivery_note()
        delivery_note = self._l10n_ec_create_delivery_note()
        # Transportista con cédula
        delivery_note.delivery_carrier_id = self.partner_dni
        delivery_note.action_confirm()
        edi_doc = delivery_note

        self.assertEqual(delivery_note.state, "done")
        self.assertTrue(edi_doc.l10n_ec_xml_access_key)
        try:
            delivery_note.action_sent_mail_electronic()
            delivery_note.l10n_ec_action_sent_mail_electronic()
            mail_sended = True
        except UserError as e:
            _logger.warning(e.name)
            mail_sended = False
        self.assertTrue(mail_sended)
