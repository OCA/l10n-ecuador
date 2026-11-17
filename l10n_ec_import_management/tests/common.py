from odoo.fields import Command

from odoo.addons.stock_landed_costs.tests.common import TestStockLandedCostsCommon


class L10nEcImportCommon(TestStockLandedCostsCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        company = cls.env.company
        cls.customs = cls.env["res.partner"].create({"name": "Customs Authority"})
        cls.vat_account = cls.company_data["default_account_expense"].copy({"code": "EC.IVA.IMP"})
        company.write({
            "l10n_ec_import_fodinfa_rate": 0.5,
            "l10n_ec_import_vat_rate": 15.0,
            "l10n_ec_customs_partner_id": cls.customs.id,
            "l10n_ec_import_vat_account_id": cls.vat_account.id,
        })
        cls.env.company.lc_journal_id = cls.stock_journal
        for xmlid in ("advalorem", "fodinfa", "ice", "freight", "insurance", "other"):
            cls.env.ref(f"l10n_ec_import_management.product_import_{xmlid}").property_account_expense_id = (
                cls.company_data["default_account_expense"]
            )
        cls.tariff = cls.env["l10n_ec.import.tariff"].create({
            "code": "8418.10.00.00",
            "name": "Refrigerators",
            "rule_ids": [
                Command.create({"rule_type": "percent", "rate": 10.0}),
                Command.create({"rule_type": "per_quantity", "amount": 0.5}),
            ],
        })
        cls.product_refrigerator.l10n_ec_tariff_id = cls.tariff
        cls.product_oven.l10n_ec_tariff_id = cls.tariff

        po = cls.env["purchase.order"].create({
            "partner_id": cls.partner_a.id,
            "order_line": [
                Command.create({
                    "product_id": cls.product_refrigerator.id,
                    "product_qty": 10,
                    "price_unit": 100.0,
                    "tax_ids": [Command.clear()],
                }),
                Command.create({
                    "product_id": cls.product_oven.id,
                    "product_qty": 5,
                    "price_unit": 200.0,
                    "discount": 10.0,
                    "tax_ids": [Command.clear()],
                }),
            ],
        })
        po.button_confirm()
        cls.receipt = po.picking_ids
        for move in cls.receipt.move_ids:
            move.quantity = move.product_uom_qty
        cls.receipt.button_validate()
        cls.po = po

    def _new_import(self, **kw):
        vals = {
            "dai_number": "028-2026-10-00012345",
            "picking_ids": [Command.set(self.receipt.ids)],
            "freight_amount": 150.0,
            "insurance_amount": 50.0,
        }
        vals.update(kw)
        imp = self.env["l10n_ec.import"].create(vals)
        imp.action_load_receipts()
        return imp

    def _line(self, imp, product):
        return imp.line_ids.filtered(lambda line: line.product_id == product)

    def _tribute(self, imp, product, ttype):
        return imp.tribute_ids.filtered(lambda t: t.product_id == product and t.tribute_type == ttype)
