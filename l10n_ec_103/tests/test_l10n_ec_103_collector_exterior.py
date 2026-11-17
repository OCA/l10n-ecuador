from datetime import date

from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon

PERIOD_START = date(2026, 8, 1)
PERIOD_FINISH = date(2026, 8, 31)


@tagged("post_install", "-at_install")
class TestL10nEc103CollectorExterior(AccountTestInvoicingCommon):
    """Non-resident boxes live behind the first digit.

    Resident boxes start with 3, non-resident boxes with 4, so the two
    blocks slice one tag pass instead of re-reading the moves -- and a
    foreign concept can never leak into 349/399 nor a resident one into
    497/498. The user classifies by choosing the concept tax; treaty and
    haven classification per payee stays manual in v1. Totals: 499 adds
    both withheld subtotals (399 + 498), 500 is case-file state defaulting
    to zero, 501 is 499 − 500.
    """

    @classmethod
    @AccountTestInvoicingCommon.setup_country("ec")
    @AccountTestInvoicingCommon.setup_chart_template("ec")
    def setUpClass(cls):
        super().setUpClass()
        cls.collector = cls.env["l10n.ec.103.collector"]
        chart = cls.env["account.chart.template"].with_company(cls.company)
        cls.tax_303 = chart.ref("tax_withhold_profit_303")
        cls.tax_410 = chart.ref("tax_withhold_profit_522A_410")
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

    def _collect_all(self, carryover=None):
        residentes = self.collector._l10n_ec_103_collect_residentes(
            self.company, PERIOD_START, PERIOD_FINISH
        )
        exterior = self.collector._l10n_ec_103_collect_exterior(
            self.company, PERIOD_START, PERIOD_FINISH
        )
        totals = self.collector._l10n_ec_103_collect_totals(
            self.company, residentes, exterior, carryover=carryover
        )
        return residentes, exterior, totals

    def test_foreign_concept(self):
        self._post_withheld(1000.0, self.tax_410)
        residentes, exterior, _totals = self._collect_all()
        self.assertEqual(exterior["410"], 1000.0)
        self.assertEqual(exterior["460"], 220.0)
        self.assertEqual(exterior["497"], 1000.0)
        self.assertEqual(exterior["498"], 220.0)
        self.assertNotIn("303", exterior)
        self.assertEqual(residentes["349"], 0.0)
        self.assertEqual(residentes["399"], 0.0)
        self.assertNotIn("410", residentes)

    def test_totals(self):
        self._post_withheld(1000.0, self.tax_303)
        self._post_withheld(1000.0, self.tax_410)
        _residentes, _exterior, totals = self._collect_all()
        self.assertEqual(totals["499"], 320.0)
        self.assertEqual(totals["500"], 0.0)
        self.assertEqual(totals["501"], 320.0)

    def test_compensation_carryover(self):
        self._post_withheld(1000.0, self.tax_303)
        _residentes, _exterior, totals = self._collect_all(carryover={"500": 20.0})
        self.assertEqual(totals["499"], 100.0)
        self.assertEqual(totals["500"], 20.0)
        self.assertEqual(totals["501"], 80.0)
