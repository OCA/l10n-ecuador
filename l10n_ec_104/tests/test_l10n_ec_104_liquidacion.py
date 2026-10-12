from datetime import date

from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon

PERIOD_START = date(2026, 8, 1)
PERIOD_FINISH = date(2026, 8, 31)


@tagged("post_install", "-at_install")
class TestL10nEc104Liquidacion(AccountTestInvoicingCommon):
    """Settlement from the collected boxes plus the month's terms.

    482 carries 429 over, 484 defaults to the VAT of the cash sales (the
    guide asks for *at least* the VAT of box 480, plus the credit VAT *as
    applicable* -- unknowable from the moves alone, so the prefill books
    the cash VAT and carries the rest to 485), and 499 is 483+484. The
    563 factor follows the guide formula literally (411+412+420+415+416+
    417+418)/419 -- note 435 is not in the numerator -- with 1.0 when 419
    is zero (no sales to apportion, documented default). 601/602 are
    mutually exclusive by construction. 615/617/618/619 and every prior-
    period carryover stay manual: cross-period state is out of v1.
    """

    @classmethod
    @AccountTestInvoicingCommon.setup_country("ec")
    @AccountTestInvoicingCommon.setup_chart_template("ec")
    def setUpClass(cls):
        super().setUpClass()
        cls.collector = cls.env["l10n.ec.104.collector"]
        chart = cls.env["account.chart.template"].with_company(cls.company)
        cls.tax_15_sale = chart.ref("tax_vat_15_411_goods")
        cls.tax_0_no_credit = chart.ref("tax_vat_413")
        cls.tax_15_purchase = chart.ref("tax_vat_15_510_sup_01")
        cls.revenue_account = cls.company_data["default_account_revenue"]
        cls.expense_account = cls.company_data["default_account_expense"]
        cls.sale_journal = cls.company_data["default_journal_sale"]
        cls.purchase_journal = cls.company_data["default_journal_purchase"]
        cls.term_30_days = cls.env["account.payment.term"].create(
            {
                "name": "30 days",
                "company_id": cls.company.id,
                "line_ids": [
                    (
                        0,
                        0,
                        {
                            "value": "percent",
                            "value_amount": 100.0,
                            "delay_type": "days_after",
                            "nb_days": 30,
                        },
                    )
                ],
            }
        )

    def _post_sale(self, price, tax, term=False):
        move = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "company_id": self.company.id,
                "partner_id": self.partner_a.id,
                "invoice_date": PERIOD_START.isoformat(),
                "date": PERIOD_START.isoformat(),
                "journal_id": self.sale_journal.id,
                "invoice_payment_term_id": term and term.id or False,
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
            }
        )
        move.action_post()
        return move

    def _post_purchase(self, price, tax):
        self._purchase_sequence = getattr(self, "_purchase_sequence", 0) + 1
        move = self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "company_id": self.company.id,
                "partner_id": self.partner_a.id,
                "l10n_latam_document_number": (
                    f"001-001-{self._purchase_sequence:09d}"
                ),
                "invoice_date": PERIOD_START.isoformat(),
                "date": PERIOD_START.isoformat(),
                "journal_id": self.purchase_journal.id,
                "invoice_line_ids": [
                    (
                        0,
                        0,
                        {
                            "name": "test line",
                            "quantity": 1.0,
                            "price_unit": price,
                            "account_id": self.expense_account.id,
                            "tax_ids": [(6, 0, [tax.id])],
                        },
                    )
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
            carryover=carryover or None,
        )

    def test_cash_settlement(self):
        self._post_sale(100.0, self.tax_15_sale)
        boxes = self._settle()
        self.assertEqual(boxes["480"], 100.0)
        self.assertEqual(boxes["481"], 0.0)
        self.assertEqual(boxes["482"], 15.0)
        self.assertEqual(boxes["483"], 0.0)
        self.assertEqual(boxes["484"], 15.0)
        self.assertEqual(boxes["485"], 0.0)
        self.assertEqual(boxes["499"], 15.0)
        self.assertEqual(boxes["563"], 1.0)
        self.assertEqual(boxes["564"], 0.0)
        self.assertEqual(boxes["565"], 0.0)
        self.assertEqual(boxes["601"], 15.0)
        self.assertEqual(boxes["602"], 0.0)
        self.assertEqual(boxes["609"], 0.0)
        self.assertEqual(boxes["620"], 15.0)
        self.assertEqual(boxes["699"], 15.0)
        self.assertEqual(boxes["799"], 0.0)
        self.assertEqual(boxes["801"], 0.0)
        self.assertEqual(boxes["859"], 15.0)

    def test_credit_sale_defers_settlement(self):
        self._post_sale(100.0, self.tax_15_sale, term=self.term_30_days)
        boxes = self._settle()
        self.assertEqual(boxes["480"], 0.0)
        self.assertEqual(boxes["481"], 100.0)
        self.assertEqual(boxes["482"], 15.0)
        self.assertEqual(boxes["484"], 0.0)
        self.assertEqual(boxes["485"], 15.0)
        self.assertEqual(boxes["499"], 0.0)
        self.assertEqual(boxes["601"], 0.0)
        self.assertEqual(boxes["602"], 0.0)
        self.assertEqual(boxes["620"], 0.0)
        self.assertEqual(boxes["699"], 0.0)
        self.assertEqual(boxes["859"], 0.0)

    def test_proportional_credit(self):
        self._post_sale(100.0, self.tax_15_sale)
        self._post_sale(100.0, self.tax_0_no_credit)
        self._post_purchase(200.0, self.tax_15_purchase)
        boxes = self._settle()
        self.assertEqual(boxes["563"], 0.5)
        self.assertEqual(boxes["564"], 15.0)
        self.assertEqual(boxes["565"], 15.0)
        self.assertEqual(boxes["601"], 0.0)
        self.assertEqual(boxes["602"], 0.0)

    def test_full_credit_exceeds_settlement(self):
        self._post_sale(100.0, self.tax_15_sale)
        self._post_purchase(200.0, self.tax_15_purchase)
        boxes = self._settle()
        self.assertEqual(boxes["563"], 1.0)
        self.assertEqual(boxes["564"], 30.0)
        self.assertEqual(boxes["565"], 0.0)
        self.assertEqual(boxes["601"], 0.0)
        self.assertEqual(boxes["602"], 15.0)
        self.assertEqual(boxes["620"], -15.0)
        self.assertEqual(boxes["699"], -15.0)
        self.assertEqual(boxes["859"], -15.0)
