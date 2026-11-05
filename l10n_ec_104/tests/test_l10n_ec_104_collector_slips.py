from datetime import date

from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon

from . import common

PERIOD_START = date(2026, 8, 1)
PERIOD_FINISH = date(2026, 8, 31)


@tagged("post_install", "-at_install")
class TestL10nEc104CollectorSlips(common.Base):
    """Slip counts (111/113/115/117/119) count documents, never amounts.

    Derived rule D8: 111 counts posted customer invoices, 113 the cancelled
    ones, 115 the posted vendor bills except sales notes (02) and purchase
    liquidations, 117 the sales notes received (02), and 119 the purchase
    liquidations emitted (``purchase_liquidation`` internal type).
    """

    @classmethod
    @AccountTestInvoicingCommon.setup_country("ec")
    @AccountTestInvoicingCommon.setup_chart_template("ec")
    def setUpClass(cls):
        super().setUpClass()
        cls.collector = cls.env["l10n.ec.104.collector"]
        chart = cls.env["account.chart.template"].with_company(cls.company)
        cls.tax_15 = chart.ref("tax_vat_15_411_goods")
        cls.tax_15_purchase = chart.ref("tax_vat_15_510_sup_01")
        cls.revenue_account = cls.company_data["default_account_revenue"]
        cls.expense_account = cls.company_data["default_account_expense"]
        cls.sale_journal = cls.company_data["default_journal_sale"]
        cls.purchase_journal = cls.company_data["default_journal_purchase"]
        common.setup_edi_aware(
            cls,
            sale_journal=cls.sale_journal,
            purchase_journal=cls.purchase_journal,
        )
        cls.doc_02 = cls.env.ref("l10n_ec.ec_dt_02")
        cls.doc_03 = cls.env.ref("l10n_ec.ec_dt_03")

    def _post_sale(self, **kwargs):
        move = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
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
                            "price_unit": 100.0,
                            "account_id": self.revenue_account.id,
                            "tax_ids": [(6, 0, [self.tax_15.id])],
                        },
                    )
                ],
                **kwargs,
            }
        )
        move.action_post()
        return move

    def _post_bill(self, **kwargs):
        # Vendor bills post through a journal with Latam documents, which
        # refuses posting without a document number. The collector never
        # reads it (that is ATS territory); the per-test counter only keeps
        # the numbers unique inside each test.
        self._purchase_sequence = getattr(self, "_purchase_sequence", 0) + 1
        values = {
            "move_type": "in_invoice",
            "company_id": self.company.id,
            "partner_id": self.partner_a.id,
            "l10n_latam_document_number": f"001-001-{self._purchase_sequence:09d}",
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
                        "price_unit": 100.0,
                        "account_id": self.expense_account.id,
                        "tax_ids": [(6, 0, [self.tax_15_purchase.id])],
                    },
                )
            ],
        }
        values.update(kwargs)
        move = self.env["account.move"].create(values)
        common.set_tax_support(move)
        move.action_post()
        return move

    def _collect(self):
        return self.collector._l10n_ec_104_collect_slips(
            self.company, PERIOD_START, PERIOD_FINISH
        )

    def test_emitted_and_cancelled_sales(self):
        self._post_sale()
        cancelled = self._post_sale()
        cancelled.button_cancel()
        slips = self._collect()
        self.assertEqual(slips["111"], 1.0)
        self.assertEqual(slips["113"], 1.0)
        self.assertEqual(slips["115"], 0.0)
        self.assertEqual(slips["117"], 0.0)
        self.assertEqual(slips["119"], 0.0)

    def test_received_bills_split_notes_and_liquidations(self):
        self._post_bill()
        self._post_bill(l10n_latam_document_type_id=self.doc_02.id)
        self._post_bill(l10n_latam_document_type_id=self.doc_03.id)
        slips = self._collect()
        self.assertEqual(slips["115"], 1.0)
        self.assertEqual(slips["117"], 1.0)
        self.assertEqual(slips["119"], 1.0)

    def test_refunds_do_not_count_as_slips(self):
        invoice = self._post_sale()
        self._post_sale(move_type="out_refund", reversed_entry_id=invoice.id)
        bill = self._post_bill()
        self._post_bill(move_type="in_refund", reversed_entry_id=bill.id)
        slips = self._collect()
        self.assertEqual(slips["111"], 1.0)
        self.assertEqual(slips["115"], 1.0)
