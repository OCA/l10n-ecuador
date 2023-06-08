from odoo.tests import Form, tagged

from odoo.addons.l10n_ec_account_edi.tests.test_edi_common import TestL10nECEdiCommon


@tagged("post_install_l10n_ec_account_edi", "post_install", "-at_install")
class TestL10nDeliveryNoteCommon(TestL10nECEdiCommon):
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

    def _l10n_ec_create_or_modify_picking(self, picking=None, delivery_note=True):
        model_picking = picking if picking else self.env["stock.picking"]
        with Form(model_picking) as form:
            form.l10n_ec_delivery_note_journal_id = self.journal
            form.l10n_ec_create_delivery_note = delivery_note
            form.l10n_ec_delivery_carrier_id = self.partner_carrier
            form.l10n_latam_internal_type = self.env["l10n_latam.document.type"].search(
                [("code", "=", "06")], limit=1
            )
            if not model_picking.id:
                form.partner_id = self.partner_dni
                form.picking_type_id = self.picking_type
                with form.move_ids_without_package.new() as line:
                    line.product_id = self.product_a
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
        self.env["res.config.settings"].write({"group_stock_adv_location": True})
        warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", self.company_data["company"].id)]
        )
        warehouse.write({"delivery_steps": "pick_pack_ship"})

    def setup_stock_traceability(self):
        self.env["res.config.settings"].write(
            {
                "group_stock_production_lot": True,
            }
        )
        self.picking_type.write({"use_create_lots": True})
        self.product_a.write({"type": "product", "tracking": "lot"})
        lot = self.env["stock.production.lot"].create(
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
            form.users.add(self.env.user)
        picking_type = self.env["stock.picking.type"].search(
            [
                ("code", "=", "incoming"),
                ("company_id", "=", self.company_data["company"].id),
            ],
            limit=1,
        )
        picking_type.write({"code": "internal"})
        return picking_type
