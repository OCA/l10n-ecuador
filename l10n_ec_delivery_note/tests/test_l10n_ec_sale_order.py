from odoo.exceptions import UserError
from odoo.tests import Form, tagged

from .test_l10n_ec_delivery_note_common import TestL10nDeliveryNoteCommon


@tagged("post_install_l10n_ec_account_edi", "post_install", "-at_install", "sale")
class TestL10nSaleOrder(TestL10nDeliveryNoteCommon):
    def test_l10n_ec_sale_order_picking_internal(self):
        """Validar creación de guia de remisión de picking
        cuando la ubicación destino es interna"""
        self.setup_edi_delivery_note()
        self.setup_multistage_routes()
        sale_order = self._l10n_ec_prepare_sale_order()
        sale_order.action_confirm()
        picking_internal = sale_order.picking_ids.search(
            [("location_dest_id.usage", "=", "internal")], limit=1, order="id asc"
        )
        picking = self._l10n_ec_create_or_modify_picking(picking=picking_internal)
        picking_context = picking.button_validate()
        self.assertTrue(picking_context)

    def test_l10n_ec_sale_order_picking_in_3_steps(self):
        """Desde acción crear una guia de remisión,de pickings
        creados desde un pedido en 3 pasos"""
        self.setup_edi_delivery_note()
        # Desactivar que exista la factura en el pedido
        self.company.l10n_ec_validate_invoice_exist = False
        self.setup_multistage_routes()
        sale_order = self._l10n_ec_prepare_sale_order()
        sale_order.action_confirm()
        pickings = sale_order.picking_ids.search([], order="id asc")
        for pick in pickings:
            picking = self._l10n_ec_create_or_modify_picking(
                picking=pick, delivery_note=False
            )

            picking.button_validate()
        model_wizard = self.env["wizard.create.delivery.note"]
        wiz = Form(model_wizard.with_context(active_ids=pickings.ids)).save()
        # Intentar crear guia de remisión de las 3 transferencias creadas
        # desde el pedido
        with self.assertRaises(UserError):
            wiz.action_create_delivery_note()
        # Crear guia con transferencia que tenga ubicacion destino diferente a interna
        internal_pickings = wiz.line_ids.filtered(
            lambda x: x.location_dest_id.usage == "internal"
        )
        wiz.line_ids = wiz.line_ids - internal_pickings
        delivery_context = wiz.action_create_delivery_note()
        delivery_note_form = Form(
            self.DeliveryNote.with_context(**delivery_context["context"])
        )

        delivery_note_form.delivery_carrier_id = self.partner_carrier
        delivery_note = delivery_note_form.save()

        delivery_note.action_confirm()
        self.assertEqual(delivery_note.state, "done")
        self.assertNotEqual(
            delivery_note.stock_picking_ids.location_dest_id.usage, "internal"
        )
        self.assertEqual(sale_order.l10n_ec_delivery_note_ids.id, delivery_note.id)

    def test_l10n_ec_picking_sale_order_invoiced(self):
        """Desde acción crear una guia de remisión
        de picking con pedido facturado"""
        self.setup_edi_delivery_note()
        sale_order = self._l10n_ec_prepare_sale_order()
        sale_order.action_confirm()
        invoice = sale_order._create_invoices()
        invoice.action_post()
        picking = sale_order.picking_ids
        picking = self._l10n_ec_create_or_modify_picking(
            picking=picking, delivery_note=False
        )
        # picking.action_set_quantities_to_reservation()
        picking.button_validate()
        model_wizard = self.env["wizard.create.delivery.note"]
        wiz = Form(model_wizard.with_context(active_ids=picking.id)).save()
        # Cancelar la factura asociada al pedido, e intentar crear guia
        with self.assertRaises(UserError):
            invoice.button_cancel()
            wiz.action_create_delivery_note()
        delivery_context = wiz.action_create_delivery_note()

        delivery_note_form = Form(
            self.DeliveryNote.with_context(**delivery_context["context"])
        )

        delivery_note_form.delivery_carrier_id = self.partner_carrier
        delivery_note = delivery_note_form.save()

        delivery_note.action_confirm()
        self.assertEqual(picking.id, delivery_note.stock_picking_ids.id)
        self.assertEqual(delivery_note.state, "done")
        self.assertEqual(sale_order.l10n_ec_delivery_note_ids.id, delivery_note.id)
        self.assertEqual(
            sale_order.action_view_l10n_ec_delivery_note()["res_id"], delivery_note.id
        )
        self.assertEqual(invoice.l10n_ec_delivery_note_ids.id, delivery_note.id)

    def test_l10n_ec_delivery_note_picking_backorder_sale_order(self):
        """Crear picking con backorder asociados a un pedido,
        y generar las guia de remisión"""
        self.setup_edi_delivery_note()
        sale_order = self._l10n_ec_prepare_sale_order()
        sale_order.action_confirm()
        picking = self._l10n_ec_create_or_modify_picking(
            picking=sale_order.picking_ids, delivery_note=True
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
        note1 = picking.l10n_ec_delivery_note_ids
        self.assertTrue(picking.backorder_ids.ids)
        self.assertEqual(picking.state, "done")
        self.assertEqual(note1.state, "done")
        # Validar el picking en backorder y crear otra guia de remisión
        picking_backorder = picking.backorder_ids
        picking_backorder.button_validate()

        note2 = picking_backorder.l10n_ec_delivery_note_ids
        self.assertEqual(picking_backorder.state, "done")
        self.assertEqual(note2.state, "done")
        self.assertEqual(sale_order.l10n_ec_delivery_note_ids, note1 + note2)
        self.assertTrue(sale_order.action_view_l10n_ec_delivery_note()["domain"])
