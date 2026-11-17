from datetime import date

from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon

PERIOD_START = date(2026, 8, 1)
PERIOD_FINISH = date(2026, 8, 31)


@tagged("post_install", "-at_install")
class TestL10nEc103CollectorResidentes(AccountTestInvoicingCommon):
    """One box mapping rule: tags decide, the collector only adds.

    The EC chart template maps every income-withholding tax to its 103
    boxes through the ``Reporte 103`` tags on the repartition lines (base
    lines carry the base boxes like 303, tax lines the withheld boxes like
    353, invoice and refund sides each with their own tags). The collector
    therefore never hardcodes a concept: it aggregates the signed balances
    of the posted vendor moves carrying those tags -- bills count positive,
    vendor credit notes count negative -- and computes the boxes the chart
    carries no tag for (subtotal 349/399).
    """

    @classmethod
    @AccountTestInvoicingCommon.setup_country("ec")
    @AccountTestInvoicingCommon.setup_chart_template("ec")
    def setUpClass(cls):
        super().setUpClass()
        cls.collector = cls.env["l10n.ec.103.collector"]
        chart = cls.env["account.chart.template"].with_company(cls.company)
        cls.tax_303 = chart.ref("tax_withhold_profit_303")
        cls.tax_307 = chart.ref("tax_withhold_profit_307")
        cls.tax_3440 = chart.ref("tax_withhold_profit_3440")
        cls.expense_account = cls.company_data["default_account_expense"]
        cls.purchase_journal = cls.company_data["default_journal_purchase"]

    def _post_withheld(self, price, tax, move_type="in_invoice", **kwargs):
        self._withhold_sequence = getattr(self, "_withhold_sequence", 0) + 1
        move = self.env["account.move"].create(
            {
                "move_type": move_type,
                "company_id": self.company.id,
                "partner_id": self.partner_a.id,
                "l10n_latam_document_number": (
                    f"001-001-{self._withhold_sequence:09d}"
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
                **kwargs,
            }
        )
        move.action_post()
        return move

    def _collect(self):
        return self.collector._l10n_ec_103_collect_residentes(
            self.company, PERIOD_START, PERIOD_FINISH
        )

    def test_standard_concept(self):
        self._post_withheld(1000.0, self.tax_303)
        boxes = self._collect()
        self.assertEqual(boxes["303"], 1000.0)
        self.assertEqual(boxes["353"], 100.0)
        self.assertEqual(boxes["349"], 1000.0)
        self.assertEqual(boxes["399"], 100.0)

    def test_mixed_concepts(self):
        self._post_withheld(1000.0, self.tax_303)
        self._post_withheld(500.0, self.tax_307)
        self._post_withheld(200.0, self.tax_3440)
        boxes = self._collect()
        self.assertEqual(boxes["303"], 1000.0)
        self.assertEqual(boxes["353"], 100.0)
        self.assertEqual(boxes["307"], 500.0)
        self.assertEqual(boxes["357"], 10.0)
        self.assertEqual(boxes["3440"], 200.0)
        self.assertEqual(boxes["3940"], 5.5)
        self.assertEqual(boxes["349"], 1700.0)
        self.assertEqual(boxes["399"], 115.5)

    def test_same_concept_credit_note_reduces_net(self):
        bill = self._post_withheld(1000.0, self.tax_303)
        self._post_withheld(
            400.0,
            self.tax_303,
            move_type="in_refund",
            reversed_entry_id=bill.id,
        )
        boxes = self._collect()
        self.assertEqual(boxes["303"], 600.0)
        self.assertEqual(boxes["353"], 60.0)
        self.assertEqual(boxes["349"], 600.0)
        self.assertEqual(boxes["399"], 60.0)

    def test_voucher_like_entry_is_read_once(self):
        # A withhold voucher is an `entry` move whose basis lines carry
        # the withhold taxes (counterpart lines ship tag-stripped). The
        # collector reads it without needing the withhold module, and a
        # bill carrying the same tax beside it would double -- one event,
        # one record.
        move = self.env["account.move"].create(
            {
                "move_type": "entry",
                "company_id": self.company.id,
                "partner_id": self.partner_a.id,
                "date": PERIOD_START.isoformat(),
                "journal_id": (
                    self.env["account.journal"]
                    .search(
                        [
                            ("company_id", "=", self.company.id),
                            ("type", "=", "general"),
                        ],
                        limit=1,
                    )
                    .id
                ),
                "line_ids": [
                    (
                        0,
                        0,
                        {
                            "name": "RET base",
                            "debit": 1000.0,
                            "account_id": self.expense_account.id,
                            "tax_ids": [(6, 0, [self.tax_303.id])],
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "name": "RET counterpart",
                            "credit": 1000.0,
                            "account_id": self.expense_account.id,
                        },
                    ),
                ],
            }
        )
        move.action_post()
        boxes = self._collect()
        self.assertEqual(boxes["303"], 1000.0)
        self.assertEqual(boxes["353"], 100.0)
