from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tests import tagged

from .common import L10nEcImportCommon


@tagged("post_install", "-at_install")
class TestL10nEcImport(L10nEcImportCommon):

    def test_01_fob_cif_and_tributes(self):
        imp = self._new_import()
        fridge, oven = self._line(imp, self.product_refrigerator), self._line(imp, self.product_oven)
        self.assertEqual(fridge.fob_amount, 1000.0)
        self.assertEqual(oven.fob_amount, 900.0, "FOB uses the discounted subtotal")

        imp.action_calculate()
        self.assertEqual(imp.state, "calculated")
        self.assertAlmostEqual(imp.amount_freight, 150.0)
        self.assertAlmostEqual(imp.amount_insurance, 50.0)
        self.assertAlmostEqual(imp.amount_cif, 2100.0)
        self.assertAlmostEqual(fridge.freight_amount, 78.95)
        self.assertAlmostEqual(fridge.cif_amount, 1105.27)

        cur = imp.currency_id
        adv = cur.round(fridge.cif_amount * 0.10 + 10 * 0.5)
        fod = cur.round(fridge.cif_amount * 0.005)
        vat = cur.round((fridge.cif_amount + adv + fod) * 0.15)
        self.assertAlmostEqual(fridge.advalorem_amount, adv)
        self.assertAlmostEqual(fridge.fodinfa_amount, fod)
        self.assertAlmostEqual(fridge.vat_amount, vat)
        self.assertAlmostEqual(
            imp.amount_tributes,
            imp.amount_advalorem + imp.amount_fodinfa + imp.amount_ice + imp.amount_vat,
        )

    def test_02_ice_enters_vat_base(self):
        imp = self._new_import()
        fridge = self._line(imp, self.product_refrigerator)
        fridge.ice_amount = 100.0
        imp.action_calculate()
        vat = self._tribute(imp, self.product_refrigerator, "vat")
        expected_base = fridge.cif_amount + fridge.advalorem_amount + fridge.fodinfa_amount + 100.0
        self.assertAlmostEqual(vat.base_amount, imp.currency_id.round(expected_base))
        self.assertAlmostEqual(imp.amount_ice, 100.0)

    def test_03_relief_requires_reason_and_survives_recalc(self):
        imp = self._new_import()
        imp.action_calculate()
        adv = self._tribute(imp, self.product_oven, "advalorem")
        adv.write({"relief_type": "percent", "relief_value": 100.0})
        self.assertEqual(adv.amount, 0.0)
        with self.assertRaises(UserError):
            imp.action_publish()
        self._tribute(imp, self.product_oven, "advalorem").relief_reason = "Trade agreement, Annex I"
        imp.action_publish()
        self.assertEqual(imp.state, "published")
        oven = self._line(imp, self.product_oven)
        self.assertEqual(oven.advalorem_amount, 0.0, "relief kept after the publish recalculation")
        vat = self._tribute(imp, self.product_oven, "vat")
        self.assertAlmostEqual(vat.base_amount, oven.cif_amount + oven.fodinfa_amount)

    def test_04_rates_frozen_when_published(self):
        imp = self._new_import()
        imp.action_publish()
        self.env.company.l10n_ec_import_vat_rate = 12.0
        self.assertEqual(imp.vat_rate, 15.0)
        with self.assertRaises(UserError):
            imp.action_calculate()

    def test_05_customs_bill_and_landed_cost(self):
        imp = self._new_import()
        imp.action_publish()

        imp.action_create_customs_bill()
        bill = imp.customs_bill_id
        self.assertEqual(bill.partner_id, self.customs)
        self.assertEqual(bill.state, "draft")
        self.assertAlmostEqual(bill.amount_total, imp.amount_tributes)
        vat_line = bill.invoice_line_ids.filtered(lambda line: line.account_id == self.vat_account)
        self.assertAlmostEqual(vat_line.price_subtotal, imp.amount_vat)
        self.assertEqual(len(bill.invoice_line_ids), 3, "Ad Valorem, FODINFA and IVA (no ICE)")

        moves = self.receipt.move_ids
        value_before = {m.product_id: m.value for m in moves}
        imp.action_create_landed_cost()
        lc = imp.landed_cost_id
        self.assertEqual(lc.vendor_bill_id, bill)
        self.assertAlmostEqual(lc.amount_total, imp.amount_advalorem + imp.amount_fodinfa)
        lc.button_validate()
        self.assertEqual(lc.state, "done")
        for move in moves:
            line = self._line(imp, move.product_id)
            self.assertAlmostEqual(
                move.value - value_before[move.product_id],
                line.advalorem_amount + line.fodinfa_amount,
                msg="each product's stock value rises exactly by its own tributes",
            )

        with self.assertRaises(UserError):
            imp.action_reset_draft()

    def test_07_print_and_excel(self):
        imp = self._new_import()
        imp.action_publish()
        action = imp.action_export_xlsx()
        self.assertEqual(action["type"], "ir.actions.act_url")
        attachment = self.env["ir.attachment"].search([("res_model", "=", imp._name), ("res_id", "=", imp.id)])
        self.assertEqual(attachment.mimetype.split(".")[-1], "sheet")
        html, _fmt = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ec_import_management.action_report_l10n_ec_import", imp.ids
        )
        self.assertIn(imp.dai_number.encode(), html)

    def test_06_freight_to_stock_and_block_rule(self):
        self.tariff.rule_ids = [
            Command.clear(),
            Command.create({"rule_type": "per_block", "amount": 3.0, "block_size": 4.0, "block_basis": "quantity"}),
            Command.create({"rule_type": "fixed", "amount": 21.0}),
        ]
        imp = self._new_import(add_freight_to_stock=True)
        imp.action_publish()
        fridge, oven = self._line(imp, self.product_refrigerator), self._line(imp, self.product_oven)
        # 10 units -> 3 blocks of 4; 5 units -> 2 blocks. Fixed 21 split by CIF.
        fixed_fridge = imp.currency_id.round(21.0 * fridge.cif_amount / imp.amount_cif)
        self.assertAlmostEqual(fridge.advalorem_amount, 9.0 + fixed_fridge)
        self.assertAlmostEqual(oven.advalorem_amount, 6.0 + (21.0 - fixed_fridge))
        imp.action_create_landed_cost()
        self.assertAlmostEqual(
            imp.landed_cost_id.amount_total,
            imp.amount_advalorem + imp.amount_fodinfa + imp.amount_freight,
        )
