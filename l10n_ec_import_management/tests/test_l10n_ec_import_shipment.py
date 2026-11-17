from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command
from odoo.tests import tagged

from .common import L10nEcImportCommon


@tagged("post_install", "-at_install")
class TestL10nEcImportShipment(L10nEcImportCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.eur = cls.setup_other_currency("EUR")  # 1 company currency = 2 EUR
        cls.forwarder = cls.env["res.partner"].create({"name": "Forwarder"})
        cls.broker = cls.env["res.partner"].create({"name": "Customs Broker"})
        country = cls.env.ref("base.ec")
        cls.port_cn = cls.env["l10n_ec.import.port"].create({
            "name": "Shanghai", "code": "CNSHA", "country_id": cls.env.ref("base.cn").id, "is_water": True,
        })
        cls.port_ec = cls.env["l10n_ec.import.port"].create({
            "name": "Guayaquil", "code": "ECGYE", "country_id": country.id, "is_water": True,
        })
        cls.container_40 = cls.env["l10n_ec.import.container.type"].create({
            "name": "40' HC", "teu": 2, "max_weight": 26000, "volume": 76,
        })

    def _new_shipment(self):
        return self.env["l10n_ec.import.shipment"].create({
            "partner_id": self.partner_a.id,
            "forwarder_id": self.forwarder.id,
            "customs_agent_id": self.broker.id,
            "transport_type": "water",
            "water_type": "fcl",
            "loading_port_id": self.port_cn.id,
            "discharging_port_id": self.port_ec.id,
            "transport_document": "MEDU1234567",
            "purchase_order_ids": [Command.set(self.po.ids)],
            "container_ids": [Command.create({
                "container_type_id": self.container_40.id,
                "name": "MSCU1234567",
                "packages": 15,
                "gross_weight": 350,
                "volume": 20,
            })],
        })

    def test_01_shipment_flow_creates_declaration(self):
        shipment = self._new_shipment()
        self.assertTrue(shipment.name.startswith("EMB/"))
        self.assertEqual(shipment.picking_ids, self.receipt)
        self.assertEqual(shipment.total_weight, 350)

        shipment.action_depart()
        self.assertEqual(shipment.state, "in_transit")
        self.assertTrue(shipment.departure_date)
        shipment.action_arrive()
        self.assertEqual(shipment.state, "arrived")
        self.assertEqual(set(shipment.event_ids.mapped("event_type")), {"arrived", "departed"})

        shipment.action_create_import()
        declaration = shipment.import_ids
        self.assertEqual(len(declaration), 1)
        self.assertEqual(declaration.picking_ids, self.receipt)
        self.assertEqual(declaration.customs_agent_id, self.broker)
        self.assertEqual(declaration.arrival_date, shipment.arrival_date)
        self.assertEqual(len(declaration.line_ids), 2)
        with self.assertRaises(UserError, msg="every receipt is already declared"):
            shipment.action_create_import()

        with self.assertRaises(UserError, msg="cannot close with a draft declaration"):
            shipment.action_done()
        declaration.action_publish()
        shipment.action_done()
        self.assertEqual(shipment.state, "done")
        with self.assertRaises(UserError):
            shipment.action_cancel()

    def test_02_cost_lines_feed_cif_with_conversion(self):
        imp = self._new_import(freight_amount=0.0, insurance_amount=0.0)
        imp.cost_line_ids = [
            Command.create({"cost_type": "freight", "partner_id": self.forwarder.id, "amount": 200.0,
                            "currency_id": self.eur.id}),
            Command.create({"cost_type": "freight", "amount": 50.0}),
            Command.create({"cost_type": "insurance", "amount": 50.0}),
            Command.create({"cost_type": "other", "amount": 80.0}),
        ]
        self.assertAlmostEqual(imp.freight_amount, 150.0, msg="200 EUR at 2.0 + 50")
        self.assertAlmostEqual(imp.insurance_amount, 50.0)
        self.assertAlmostEqual(imp.amount_other_costs, 80.0)
        imp.action_calculate()
        self.assertAlmostEqual(imp.amount_cif, 2100.0, msg="other costs never enter the CIF")

    def test_03_other_costs_reach_stock_value(self):
        imp = self._new_import()
        imp.cost_line_ids = [
            Command.create({"cost_type": "other", "name": "Port handling", "amount": 60.0}),
            Command.create({"cost_type": "other", "name": "Already in a bill", "amount": 99.0, "add_to_stock": False}),
        ]
        imp.action_publish()
        imp.action_create_landed_cost()
        lc = imp.landed_cost_id
        self.assertAlmostEqual(lc.amount_total, imp.amount_advalorem + imp.amount_fodinfa + 60.0)
        moves = self.receipt.move_ids
        value_before = sum(moves.mapped("value"))
        lc.button_validate()
        self.assertAlmostEqual(sum(moves.mapped("value")) - value_before, lc.amount_total)

    def test_04_container_capacity(self):
        shipment = self._new_shipment()
        with self.assertRaises(ValidationError):
            shipment.container_ids.gross_weight = 30000
