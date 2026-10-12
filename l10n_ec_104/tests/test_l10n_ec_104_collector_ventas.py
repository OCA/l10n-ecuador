from datetime import date

from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon

PERIOD_START = date(2026, 8, 1)
PERIOD_FINISH = date(2026, 8, 31)


@tagged("post_install", "-at_install")
class TestL10nEc104CollectorVentas(AccountTestInvoicingCommon):
    """One box mapping rule: tags decide, the collector only adds.

    The EC chart template already maps every sales tax to its 104 boxes
    through the ``Reporte 104`` tags on the repartition lines (e.g.
    ``tax_vat_15_411_goods`` carries 401/411 on the base and 421 on the tax).
    The collector therefore never hardcodes a rate: it aggregates the signed
    balances of the posted lines carrying those tags, and computes the
    total boxes (409/419/429) and the rate-difference adjustments (423/424)
    the chart carries no tag for.
    """

    @classmethod
    @AccountTestInvoicingCommon.setup_country("ec")
    @AccountTestInvoicingCommon.setup_chart_template("ec")
    def setUpClass(cls):
        super().setUpClass()
        cls.collector = cls.env["l10n.ec.104.collector"]
        chart = cls.env["account.chart.template"].with_company(cls.company)
        cls.tax_15 = chart.ref("tax_vat_15_411_goods")
        cls.tax_12 = chart.ref("tax_vat_411_goods")
        cls.tax_0_credit = chart.ref("tax_vat_415_goods")
        cls.tax_0_no_credit = chart.ref("tax_vat_413")
        cls.tax_5 = chart.ref("tax_vat_05_411_goods")
        cls.revenue_account = cls.company_data["default_account_revenue"]
        cls.sale_journal = cls.company_data["default_journal_sale"]

    def _post_sale(self, price, tax, move_type="out_invoice", **kwargs):
        move = self.env["account.move"].create(
            {
                "move_type": move_type,
                "company_id": self.company.id,
                "partner_id": self.partner_a.id,
                "invoice_date": PERIOD_START.isoformat(),
                "date": PERIOD_START.isoformat(),
                "journal_id": self.sale_journal.id,
                "invoice_line_ids": [
                    (
                        0,
                        0,
                        {
                            "name": "test line",
                            "quantity": 1.0,
                            "price_unit": price,
                            "account_id": self.revenue_account.id,
                            "tax_ids": [(6, 0, [tax.id])],
                        },
                    )
                ],
                **kwargs,
            }
        )
        move.action_post()
        return move

    def _collect(self):
        return self.collector._l10n_ec_104_collect_ventas(
            self.company, PERIOD_START, PERIOD_FINISH
        )

    def test_standard_rate_sale(self):
        self._post_sale(100.0, self.tax_15)
        boxes = self._collect()
        self.assertEqual(boxes["401"], 100.0)
        self.assertEqual(boxes["411"], 100.0)
        self.assertEqual(boxes["421"], 15.0)
        self.assertEqual(boxes["409"], 100.0)
        self.assertEqual(boxes["419"], 100.0)
        self.assertEqual(boxes["429"], 15.0)
        self.assertEqual(boxes["423"], 0.0)
        self.assertEqual(boxes["424"], 0.0)

    def test_mixed_rates_sale(self):
        self._post_sale(200.0, self.tax_0_no_credit)
        self._post_sale(300.0, self.tax_0_credit)
        self._post_sale(100.0, self.tax_5)
        boxes = self._collect()
        self.assertEqual(boxes["403"], 200.0)
        self.assertEqual(boxes["413"], 200.0)
        self.assertEqual(boxes["405"], 300.0)
        self.assertEqual(boxes["415"], 300.0)
        self.assertEqual(boxes["425"], 100.0)
        self.assertEqual(boxes["435"], 100.0)
        self.assertEqual(boxes["445"], 5.0)
        self.assertEqual(boxes["409"], 600.0)
        self.assertEqual(boxes["419"], 600.0)
        self.assertEqual(boxes["429"], 5.0)

    def test_same_rate_credit_note_reduces_net(self):
        invoice = self._post_sale(100.0, self.tax_15)
        self._post_sale(
            40.0,
            self.tax_15,
            move_type="out_refund",
            reversed_entry_id=invoice.id,
        )
        boxes = self._collect()
        self.assertEqual(boxes["401"], 100.0)
        self.assertEqual(boxes["411"], 60.0)
        self.assertEqual(boxes["421"], 9.0)
        self.assertEqual(boxes["423"], 0.0)
        self.assertEqual(boxes["424"], 0.0)
        self.assertEqual(boxes["429"], 9.0)

    def test_different_rate_credit_note_adjusts_in_favor(self):
        invoice = self._post_sale(100.0, self.tax_15)
        self._post_sale(
            100.0,
            self.tax_12,
            move_type="out_refund",
            reversed_entry_id=invoice.id,
        )
        boxes = self._collect()
        # 15.0 invoiced, 12.0 credited back at the lower rate.
        self.assertEqual(boxes["421"], 3.0)
        # Absolute difference booked as adjustment in favor (424).
        self.assertEqual(boxes["424"], 3.0)
        self.assertEqual(boxes["423"], 0.0)
        self.assertEqual(boxes["429"], 0.0)
