from odoo.exceptions import UserError
from odoo.tests import Form, tagged

from .test_l10n_ec_delivery_note_common import TestL10nDeliveryNoteCommon


@tagged("post_install_l10n", "post_install", "-at_install")
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
        picking = self._l10n_ec_create_or_modify_picking(
            picking=picking_internal, delivery_note=False
        )
        self._l10n_ec_set_done_quantities(picking)
        picking.button_validate()
        # El asistente ``stock.immediate.transfer`` que rechazaba estas
        # transferencias desapareció en Odoo 19: el rechazo de las
        # transferencias internas creadas desde un pedido vive ahora en el
        # asistente de varias transferencias.
        model_wizard = self.env["wizard.create.delivery.note"]
        with self.assertRaises(UserError):
            wiz = Form(model_wizard.with_context(active_ids=picking.ids)).save()
            wiz.action_create_delivery_note()

    def test_l10n_ec_sale_order_picking_in_3_steps(self):
        """Desde acción crear una guia de remisión,de pickings
        creados desde un pedido en 3 pasos"""
        self.setup_edi_delivery_note()
        # Desactivar que exista la factura en el pedido
        self.company.l10n_ec_validate_invoice_exist = False
        self.setup_multistage_routes()
        sale_order = self._l10n_ec_prepare_sale_order()
        sale_order.action_confirm()
        # Odoo 19 chains the three steps with "push" rules: confirming the order
        # only launches the first (pick) transfer and each validated transfer
        # triggers the next one, so the whole chain is walked here.
        handled_pickings = self.env["stock.picking"]
        while True:
            pickings = sale_order.picking_ids - handled_pickings
            if not pickings:
                break
            for pick in pickings:
                picking = self._l10n_ec_create_or_modify_picking(
                    picking=pick, delivery_note=False
                )
                self._l10n_ec_set_done_quantities(picking)
                picking.button_validate()
                handled_pickings |= picking
        pickings = sale_order.picking_ids
        model_wizard = self.env["wizard.create.delivery.note"]
        wiz = Form(model_wizard.with_context(active_ids=pickings.ids)).save()
        # Intentar crear guia de remisión de las 3 transferencias del pedido
        with self.assertRaises(UserError):
            wiz.action_create_delivery_note()
        # Crear guia con transferencia que tenga ubicacion destino diferente a interna
        internal_pickings = wiz.line_ids.filtered(
            lambda x: x.location_dest_id.usage == "internal"
        )
        wiz.line_ids = wiz.line_ids - internal_pickings
        delivery_context = wiz.action_create_delivery_note()
        delivery_note = Form(
            self.DeliveryNote.with_context(**delivery_context["context"])
        ).save()
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
        self._l10n_ec_set_done_quantities(picking)
        picking.button_validate()
        model_wizard = self.env["wizard.create.delivery.note"]
        wiz = Form(model_wizard.with_context(active_ids=picking.id)).save()
        # Cancelar la factura asociada al pedido, e intentar crear guia
        with self.assertRaises(UserError):
            invoice.button_cancel()
            wiz.action_create_delivery_note()
        delivery_context = wiz.action_create_delivery_note()
        delivery_note = Form(
            self.DeliveryNote.with_context(**delivery_context["context"])
        ).save()
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
        picking.move_ids.product_uom_qty = 5
        picking.action_confirm()
        self._l10n_ec_create_move_line(picking, quantity=1)
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
        self._l10n_ec_set_done_quantities(picking_backorder)
        picking_backorder_context = picking_backorder.button_validate()
        # El popup de guía de remisión reemplaza al asistente de transferencia
        # inmediata que creaba la segunda guía en Odoo 15.
        wiz = Form(
            self.env[picking_backorder_context["res_model"]].with_context(
                **picking_backorder_context["context"]
            )
        ).save()
        wiz.action_create_delivery_note()
        note2 = picking_backorder.l10n_ec_delivery_note_ids
        self.assertEqual(picking_backorder.state, "done")
        self.assertEqual(note2.state, "done")
        self.assertEqual(sale_order.l10n_ec_delivery_note_ids, note1 + note2)
        self.assertTrue(sale_order.action_view_l10n_ec_delivery_note()["domain"])
