from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import Form, tagged

from .test_l10n_ec_delivery_note_common import TestL10nDeliveryNoteCommon


@tagged("post_install_l10n_ec_account_edi", "post_install", "-at_install", "stock")
class TestL10nStockPicking(TestL10nDeliveryNoteCommon):
    def test_l10n_ec_check_validate_picking(self):
        """Restricciones al validar una transferencia"""
        self.setup_edi_delivery_note()
        picking = self._l10n_ec_create_or_modify_picking()
        # Validar sin productos
        with self.assertRaises(UserError):
            picking.button_validate()
        # Validar sin cantidad reservada
        with self.assertRaises(UserError):
            picking.move_ids_without_package.product_id = False
            picking.button_validate()

    def test_l10n_ec_immediate_picking(self):
        """Test transferencia inmediata"""
        self.setup_edi_delivery_note()
        picking = self._l10n_ec_create_or_modify_picking(
            delivery_note=False, quantity=1
        )
        picking.action_confirm()
        picking.button_validate()
        self.assertTrue(picking.state, "done")

    def test_l10n_ec_picking_backorder(self):
        """Transferencia con Backorder"""
        self.setup_edi_delivery_note()
        picking = self._l10n_ec_create_or_modify_picking(
            delivery_note=False, quantity=1
        )
        picking.move_ids_without_package.product_uom_qty = 5
        picking.action_confirm()
        move_form = Form(
            picking.move_ids_without_package, view="stock.view_stock_move_operations"
        )
        with move_form.move_line_ids.new() as line:
            line.quantity = 1
        move_form.save()
        picking_context = picking.button_validate()
        wiz = Form(
            self.env[picking_context["res_model"]].with_context(
                **picking_context["context"]
            )
        ).save()
        wiz.process()
        self.assertTrue(picking.backorder_ids.ids)
        self.assertEqual(picking.state, "done")

    def test_l10n_ec_picking_cancel_backorder(self):
        """Transferencia cancelando Backorder"""
        self.setup_edi_delivery_note()
        picking = self._l10n_ec_create_or_modify_picking(
            delivery_note=False, quantity=1
        )
        picking.move_ids_without_package.product_uom_qty = 5
        picking.action_confirm()
        move_form = Form(
            picking.move_ids_without_package, view="stock.view_stock_move_operations"
        )
        with move_form.move_line_ids.new() as line:
            line.quantity = 1
        move_form.save()
        picking_context = picking.button_validate()
        wiz = Form(
            self.env[picking_context["res_model"]].with_context(
                **picking_context["context"]
            )
        ).save()
        wiz.process_cancel_backorder()
        self.assertFalse(picking.backorder_ids.ids)
        self.assertEqual(picking.state, "done")

    def test_l10n_ec_picking_stock_lots(self):
        """Transferencia y guía con trazabilidad por lotes"""
        self.setup_edi_delivery_note()
        lot = self.setup_stock_traceability()
        picking = self._l10n_ec_create_or_modify_picking(quantity=1)
        picking.action_confirm()
        # Validar sin escoger el lote
        with self.assertRaises(UserError):
            picking.move_ids_without_package.quantity = 1
            picking.button_validate()

        picking.move_line_ids.quantity = 1
        picking.move_line_ids.lot_id = lot

        picking.button_validate()

        delivery_note = picking.l10n_ec_delivery_note_ids
        self.assertEqual(picking.state, "done")
        self.assertEqual(delivery_note.state, "done")
        stock_move_line = picking.move_line_ids
        self.assertRecordValues(
            delivery_note.delivery_line_ids,
            [
                {
                    "product_id": stock_move_line.product_id.id,
                    "product_qty": stock_move_line.quantity,
                    "product_uom_id": stock_move_line.product_uom_id.id,
                    "production_lot_id": stock_move_line.lot_id.id,
                }
            ],
        )

    def test_l10n_ec_picking_backorder_delivery_note(self):
        """Transferencia con Backorder creando guía de remisión"""
        self.setup_edi_delivery_note()
        picking = self._l10n_ec_create_or_modify_picking(quantity=1)

        for move in picking.move_ids_without_package:
            move.quantity = 2
            move.product_uom_qty = 5
            move.picked = True

        picking.action_confirm()
        move_form = Form(
            picking.move_ids_without_package, view="stock.view_stock_move_operations"
        )
        move_form.save()
        picking_context = picking.button_validate()
        wiz = Form(
            self.env[picking_context["res_model"]].with_context(
                **picking_context["context"]
            )
        ).save()
        wiz.process()
        self.assertTrue(picking.backorder_ids.ids)
        self.assertEqual(picking.state, "done")
        self.assertEqual(picking.l10n_ec_delivery_note_ids.state, "done")

    def test_l10n_ec_picking_cancel_backorder_delivery_note(self):
        """Transferencia cancelando Backorder, creando guia de remisión"""
        self.setup_edi_delivery_note()
        picking = self._l10n_ec_create_or_modify_picking(quantity=5)

        for move in picking.move_ids_without_package:
            move.quantity = 2
            move.product_uom_qty = 5
            move.picked = True

        picking.action_confirm()
        move_form = Form(
            picking.move_ids_without_package, view="stock.view_stock_move_operations"
        )
        with move_form.move_line_ids.new() as line:
            line.quantity = 1

        move_form.save()
        picking_context = picking.button_validate()
        wiz = Form(
            self.env[picking_context["res_model"]].with_context(
                **picking_context["context"]
            )
        ).save()
        wiz.process_cancel_backorder()
        self.assertFalse(picking.backorder_ids.ids)
        # TODO Create delivery
        self.assertEqual(picking.state, "done")
        self.assertEqual(picking.l10n_ec_delivery_note_ids.state, "done")

    def test_l10n_ec_wizard_create_delivery_note(self):
        """Pruebas en wizard de crear guia de remisión"""
        self.setup_edi_delivery_note()

        picking = self._l10n_ec_create_or_modify_picking(quantity=1)
        picking.action_confirm()
        picking.button_validate()

        self.assertEqual(picking.delivery_date, picking.transfer_date)
        delivery_date_1 = picking.delivery_date
        picking.transfer_date = False
        self.assertEqual(picking.delivery_date, delivery_date_1)
        picking.transfer_date = fields.Date.today() - timedelta(days=3)
        self.assertNotEqual(picking.delivery_date, picking.transfer_date)
        with self.assertRaises(UserError):
            picking.delivery_date = picking.transfer_date - timedelta(days=1)

    def test_l10n_ec_process_picking_note_sri(self):
        """Validar y enviar al SRI una guía de remisión
        creada desde el picking, transferencia inmediata"""
        self.setup_edi_delivery_note()
        picking = self._l10n_ec_create_or_modify_picking(quantity=1)
        # Asociar el partner a una compañia
        picking.partner_id.parent_id = self.company_data["company"].partner_id.id
        picking.action_confirm()
        picking.button_validate()

        delivery_note = picking.l10n_ec_delivery_note_ids
        self.assertEqual(picking.state, "done")
        self.assertEqual(delivery_note.state, "done")
        self.assertEqual(delivery_note.partner_id, picking.partner_id.parent_id)
        edi_doc = delivery_note

        self.assertTrue(edi_doc.l10n_ec_xml_access_key)
        self.assertTrue(picking.l10n_ec_do_print_delivery_notes())

    def test_l10n_ec_internal_picking_delivery_note(self):
        """Validar y enviar al SRI una guía de remisión
        de transferencia interna"""
        self.setup_edi_delivery_note()
        picking_type_internal = self.setup_storage_locations_for_internal_picking()
        picking = self._l10n_ec_create_or_modify_picking(
            picking_type_internal=picking_type_internal, quantity=1
        )
        picking.action_confirm()
        picking.button_validate()

        delivery_note = picking.l10n_ec_delivery_note_ids
        self.assertEqual(delivery_note.delivery_note_type, "internal")
        self.assertTrue(picking.state, "done")
        self.assertTrue(delivery_note.state, "done")
        edi_doc = delivery_note

        self.assertTrue(edi_doc.l10n_ec_xml_access_key)

    def test_l10n_ec_many_picking_in_delivery_note(self):
        """Desde acción crear una guia de remisión de varios picking"""
        self.setup_edi_delivery_note()
        for i in range(5):
            picking = self._l10n_ec_create_or_modify_picking(
                delivery_note=False, quantity=1
            )
            # Cambiar el partner en 2 transferencias
            if i > 2:
                picking.partner_id = self.partner_ruc.id
            picking.action_confirm()
            picking.button_validate()
        pickings = self.env["stock.picking"].search([])
        model_wizard = self.env["wizard.create.delivery.note"]
        # Intentar crear guia de remisión de todas las transferencias
        with self.assertRaises(UserError):
            Form(model_wizard.with_context(active_ids=pickings.ids))
        # Solo transferencias del mismo partner
        pickings_filtered = pickings.search([("partner_id", "=", self.partner_dni.id)])

        wiz = Form(model_wizard.with_context(active_ids=pickings_filtered.ids)).save()
        for pick in wiz.line_ids:
            self.assertTrue(
                pick.picking_id.state == "done"
                and pick.picking_id.l10n_ec_delivery_note_ids.id is False
            )
        delivery_context = wiz.action_create_delivery_note()

        delivery_note_form = Form(
            self.DeliveryNote.with_context(**delivery_context["context"])
        )
        delivery_note_form.delivery_carrier_id = self.partner_carrier
        delivery_note = delivery_note_form.save()

        self.assertListEqual(delivery_note.stock_picking_ids.ids, pickings_filtered.ids)
        self.assertEqual(delivery_note.partner_id, self.partner_dni)
        # Intentar crear otra guia de remisión de las mismas transferencias
        wiz2 = Form(model_wizard.with_context(active_ids=pickings_filtered.ids)).save()
        self.assertFalse(wiz2.line_ids)
        # validar guía y enviar al SRI
        delivery_note.action_confirm()
        self.assertEqual(delivery_note.state, "done")
        # Cambiar a estado cancelado la guia de remisión y
        # volver a crear guía con las mismas transferencias
        delivery_note.action_cancel()
        self.assertEqual(delivery_note.state, "cancel")
        wiz3 = Form(model_wizard.with_context(active_ids=pickings_filtered.ids)).save()
        delivery_context = wiz3.action_create_delivery_note()

        delivery_note_form_new = Form(
            self.DeliveryNote.with_context(**delivery_context["context"])
        )

        delivery_note_form_new.delivery_carrier_id = self.partner_carrier
        delivery_note_new = delivery_note_form_new.save()

        self.assertListEqual(
            delivery_note.stock_picking_ids.ids, delivery_note_new.stock_picking_ids.ids
        )
