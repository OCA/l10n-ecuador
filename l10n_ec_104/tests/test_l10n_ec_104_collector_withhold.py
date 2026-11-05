from datetime import date

from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon

from . import common

PERIOD_START = date(2026, 8, 1)
PERIOD_FINISH = date(2026, 8, 31)


@tagged("post_install", "-at_install")
class TestL10nEc104CollectorWithhold(common.Base):
    """Withhold boxes read the voucher (`entry`) moves, filed positive.

    Derived rules D6/D9: the withhold flow books the 07 as an `entry`
    (invoices alone left every box at zero on the November seed), the sale
    voucher 609 line as a debit (filed as-is) and the purchase 72x lines as
    credits (negated). Tags decide: no other tax publishes 609/721–731.
    """

    @classmethod
    @AccountTestInvoicingCommon.setup_country("ec")
    @AccountTestInvoicingCommon.setup_chart_template("ec")
    def setUpClass(cls):
        super().setUpClass()
        cls.collector = cls.env["l10n.ec.104.collector"]
        chart = cls.env["account.chart.template"].with_company(cls.company)
        cls.tax_15_sale = chart.ref("tax_vat_15_411_goods")
        cls.tax_15_purchase = chart.ref("tax_vat_15_510_sup_01")
        cls.revenue_account = cls.company_data["default_account_revenue"]
        cls.expense_account = cls.company_data["default_account_expense"]
        cls.sale_journal = cls.company_data["default_journal_sale"]
        cls.purchase_journal = cls.company_data["default_journal_purchase"]
        cls.misc_journal = cls.company_data["default_journal_misc"]
        common.setup_edi_aware(
            cls,
            sale_journal=cls.sale_journal,
            purchase_journal=cls.purchase_journal,
        )

    def _post_tagged_entry(self, tag_name, balance):
        tag = self.env["account.account.tag"].search([("name", "=", tag_name)], limit=1)
        self.assertTrue(tag, f"missing tag {tag_name}")
        move = self.env["account.move"].create(
            {
                "move_type": "entry",
                "company_id": self.company.id,
                "date": PERIOD_START.isoformat(),
                "journal_id": self.misc_journal.id,
                "line_ids": [
                    (
                        0,
                        0,
                        {
                            "name": "tagged leg",
                            "account_id": self.expense_account.id,
                            "balance": balance,
                            "tax_tag_ids": [(6, 0, [tag.id])],
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "name": "offset leg",
                            "account_id": self.expense_account.id,
                            "balance": -balance,
                        },
                    ),
                ],
            }
        )
        move.action_post()
        return move

    def _settle(self, **carryover):
        ventas = self.collector._l10n_ec_104_collect_ventas(
            self.company, PERIOD_START, PERIOD_FINISH
        )
        compras = self.collector._l10n_ec_104_collect_compras(
            self.company, PERIOD_START, PERIOD_FINISH
        )
        return self.collector._l10n_ec_104_collect_liquidacion(
            self.company,
            PERIOD_START,
            PERIOD_FINISH,
            ventas,
            compras,
            carryover=carryover or {},
        )

    def test_sale_voucher_feeds_609_positive(self):
        # The sale voucher books the withheld IVA as a debit (+36.0).
        self._post_tagged_entry("609 (Reporte 104)", 36.0)
        boxes = self._settle()
        self.assertEqual(boxes["609"], 36.0)

    def test_purchase_voucher_feeds_727_positive(self):
        # The purchase voucher books the retained IVA as a credit (−75.0).
        self._post_tagged_entry("727 (Reporte 104)", -75.0)
        boxes = self._settle()
        self.assertEqual(boxes["727"], 75.0)
        self.assertEqual(boxes["799"], 75.0)
        self.assertEqual(boxes["801"], 75.0)

    def test_purchase_thirty_percent_bucket_feeds_725(self):
        # Same loop as 727: the November seed has no 30% purchase voucher,
        # the December demo seed does (45.00 on its skeleton 07).
        self._post_tagged_entry("725 (Reporte 104)", -30.0)
        boxes = self._settle()
        self.assertEqual(boxes["725"], 30.0)
        self.assertEqual(boxes["727"], 0.0)
        self.assertEqual(boxes["799"], 30.0)

    def test_withhold_boxes_flow_into_settlement(self):
        self._post_tagged_entry("609 (Reporte 104)", 36.0)
        self._post_tagged_entry("727 (Reporte 104)", -75.0)
        boxes = self._settle()
        # 620 subtracts the filed 609: a withholding in our favor lowers it.
        self.assertEqual(boxes["620"], boxes["601"] - boxes["602"] - 36.0)
        self.assertEqual(boxes["859"], boxes["699"] + 75.0)
