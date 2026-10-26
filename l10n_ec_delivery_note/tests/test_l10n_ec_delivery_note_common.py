from odoo.tests import Form, tagged

from odoo.addons.l10n_ec_account_edi.tests.test_edi_common import TestL10nECEdiCommon


@tagged("post_install_l10n", "post_install", "-at_install")
class TestL10nDeliveryNoteCommon(TestL10nECEdiCommon):
    @classmethod
    def get_default_groups(cls):
        # Odoo 19 runs the tests as a dedicated user built from these groups, and
        # the accounting default groups do not include the sales ones, so
        # ``sale.order`` records could not even be created without this.
        groups = super().get_default_groups()
        return groups | cls.quick_ref("sales_team.group_sale_manager")

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Model
        cls.DeliveryNote = cls.env["l10n_ec.delivery.note"]
        cls.partner_carrier = cls.Partner.create(
            {
                "name": "Partner Carrier",
                "vat": "1313109678001",
                "l10n_latam_identification_type_id": cls.env.ref("l10n_ec.ec_ruc").id,
                "country_id": cls.env.ref("base.ec").id,
                "l10n_ec_is_carrier": True,
                "l10n_ec_car_plate": "ABC1234",
            }
        )
        cls.partner_dni.write({"street": "Machala"})
        cls.journal_values = {
            "name": "Journal Delivery Note",
            "company_id": cls.company.id,
            "l10n_ec_emission_address_id": cls.partner_contact.id,
            "l10n_latam_use_documents": True,
            "l10n_ec_entity": "001",
            "l10n_ec_emission": "001",
            "l10n_ec_emission_type": "electronic",
            "type": "sale",
            "code": "GR",
        }
        cls.journal = cls.Journal.sudo().create(cls.journal_values)
        cls.company.l10n_ec_delivery_note_version = False
        cls.picking_type = cls.env["stock.picking.type"].search(
            [
                ("company_id", "=", cls.company_data["company"].id),
                ("code", "=", "outgoing"),
            ]
        )
        cls.picking_type.use_existing_lots = False

    def _l10n_ec_set_done_quantities(self, picking, quantity=None):
        """Set the quantity picked on every move of ``picking``.

        Replacement for ``stock.picking.action_set_quantities_to_reservation()``:
        Odoo 19 keeps a single ``quantity`` field on the move, and the core
        tests set it the same way (``addons/stock/tests/test_move2.py``).
        ``quantity`` defaults to the whole demand; pass a lower one to pick
        only part of the transfer, which is what creates a backorder.
        """
        picking.action_assign()
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty if quantity is None else quantity
        return picking

    def _l10n_ec_create_move_line(self, picking, quantity=1, lot=None):
        """Create the ``stock.move.line`` of ``picking`` with its done quantity.

        Odoo 19 creates move lines while reserving, and there is no free stock
        for the products these tests deliver, so ``action_assign()`` leaves the
        transfers without a single line. Writing ``stock.move.quantity`` does not
        work either, so the line is created by hand, the way the core 19 stock
        tests do it (``addons/stock/tests/test_immediate.py``).
        """
        move = picking.move_ids[:1]
        return self.env["stock.move.line"].create(
            {
                # ``picking_id`` is not filled from ``move_id`` in Odoo 19, it
                # has to be given or the line stays out of the transfer.
                "picking_id": picking.id,
                "move_id": move.id,
                "product_id": move.product_id.id,
                # ``stock.move.product_uom_id`` was renamed to ``product_uom``
                "product_uom_id": move.product_uom.id,
                "lot_id": lot.id if lot else False,
                "quantity": quantity,
            }
        )

    def _l10n_ec_create_delivery_note(self):
        with Form(self.DeliveryNote) as form:
            form.journal_id = self.journal
            form.partner_id = self.partner_dni
            form.delivery_carrier_id = self.partner_carrier
            form.motive = "Traslado de mercaderia"
            form.rise = "1234"
            form.dau = "1234"
            with form.delivery_line_ids.new() as line:
                line.product_id = self.product_a
                line.product_qty = 1
        return form.save()

    def _l10n_ec_create_delivery_note_without_journal(self):
        with Form(self.DeliveryNote) as form:
            form.partner_id = self.partner_dni
            form.delivery_carrier_id = self.partner_carrier
            form.motive = "Traslado de mercaderia"
            form.rise = "1234"
            form.dau = "1234"
            with form.delivery_line_ids.new() as line:
                line.product_id = self.product_a
                line.product_qty = 1
        return form.save()

    def _l10n_ec_create_or_modify_picking(
        self, picking=None, delivery_note=True, demand=1
    ):
        model_picking = picking if picking else self.env["stock.picking"]
        with Form(model_picking) as form:
            # ``l10n_ec_delivery_carrier_id`` is invisible while
            # ``l10n_ec_create_delivery_note`` is False, and a form cannot be
            # written on an invisible field, so the checkbox goes on first and
            # is cleared at the end when no delivery note is wanted.
            form.l10n_ec_create_delivery_note = True
            form.l10n_ec_delivery_note_journal_id = self.journal
            form.l10n_ec_delivery_carrier_id = self.partner_carrier
            form.l10n_latam_internal_type = self.env["l10n_latam.document.type"].search(
                [("code", "=", "06")], limit=1
            )
            if not model_picking.id:
                form.partner_id = self.partner_dni
                form.picking_type_id = self.picking_type
                # ``stock.picking.move_ids_without_package`` no longer exists in
                # Odoo 19, the moves live directly in ``move_ids``.
                with form.move_ids.new() as line:
                    line.product_id = self.product_a
                    # ``stock.move.product_uom_qty`` defaults to zero in Odoo 19
                    # and no onchange fills it anymore, the demand has to be
                    # given as the user would type it.
                    line.product_uom_qty = demand
            if not delivery_note:
                form.l10n_ec_create_delivery_note = False
        return form.save()

    def _l10n_ec_prepare_sale_order(self):
        with Form(self.env["sale.order"]) as form:
            form.partner_id = self.partner_dni
            with form.order_line.new() as line:
                line.product_id = self.product_a
        return form.save()

    def setup_edi_delivery_note(self):
        self._setup_edi_company_ec()
        self.company.write(
            {
                "l10n_ec_delivery_note_version": "1.1.0",
                "l10n_ec_validate_invoice_exist": True,
                "l10n_ec_delivery_note_days": 2,
            }
        )
        self.journal.write({"l10n_ec_emission_address_id": self.partner_contact.id})

    def setup_multistage_routes(self):
        """Configurar ruta de salida de 3 pasos en almacen al
        procesar movimientos de productos en pedidos"""
        # Odoo 19 creates the intermediate locations and picking types straight
        # from the warehouse, the way the core tests do it
        # (``addons/sale_stock/tests/test_sale_stock.py``).
        warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", self.company_data["company"].id)], limit=1
        )
        warehouse.delivery_steps = "pick_pack_ship"
        return warehouse

    def setup_stock_traceability(self):
        self.env["res.config.settings"].write(
            {
                "group_stock_production_lot": True,
            }
        )
        self.picking_type.write({"use_create_lots": True})
        # ``product.template.type`` lost its "product" value in Odoo 19, goods
        # are now flagged with ``is_storable``.
        self.product_a.write({"is_storable": True, "tracking": "lot"})
        # ``stock.production.lot`` was renamed to ``stock.lot``.
        lot = self.env["stock.lot"].create(
            {
                "name": "0001",
                "product_id": self.product_a.id,
                "company_id": self.company_data["company"].id,
            }
        )
        return lot

    def setup_storage_locations_for_internal_picking(self):
        """Activar storage locations para realizar transferencias internas"""
        with Form(self.env.ref("stock.group_stock_multi_locations")) as form:
            # ``res.groups.users`` was renamed to ``user_ids`` in Odoo 19.
            form.user_ids.add(self.env.user)
        picking_type = self.env["stock.picking.type"].search(
            [
                ("code", "=", "incoming"),
                ("company_id", "=", self.company_data["company"].id),
            ],
            limit=1,
        )
        picking_type.write({"code": "internal"})
        return picking_type
