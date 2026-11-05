from datetime import date

from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon

from . import common

PERIOD_START = date(2026, 8, 1)
PERIOD_FINISH = date(2026, 8, 31)


@tagged("post_install", "-at_install")
class TestL10nEc104CollectorCompras(common.Base):
    """Mirror of the sales collector with purchase signs.

    Vendor bills are debit-positive and core reads the purchase boxes with
    positive formulas (``500 (Reporte 104)``), so the collector adds every
    tagged balance uniformly: bills count positive, vendor credit notes
    count negative, and the net boxes come out with no special case. The
    totals (509/519/529) and the rate-difference adjustments (526/527) carry
    no tag in the chart and are computed, exactly like 409/419/429/423/424
    on the sales side.
    """

    @classmethod
    @AccountTestInvoicingCommon.setup_country("ec")
    @AccountTestInvoicingCommon.setup_chart_template("ec")
    def setUpClass(cls):
        super().setUpClass()
        cls.collector = cls.env["l10n.ec.104.collector"]
        chart = cls.env["account.chart.template"].with_company(cls.company)
        cls.tax_15 = chart.ref("tax_vat_15_510_sup_01")
        cls.tax_12 = chart.ref("tax_vat_510_sup_01")
        cls.tax_0 = chart.ref("tax_vat_517_sup_02")
        cls.tax_no_credit = chart.ref("tax_vat_15_512_sup_04")
        cls.tax_5 = chart.ref("tax_vat_05_510_sup_01")
        cls.expense_account = cls.company_data["default_account_expense"]
        cls.purchase_journal = cls.company_data["default_journal_purchase"]
        common.setup_edi_aware(cls, purchase_journal=cls.purchase_journal)

    def _post_purchase(self, price, tax, move_type="in_invoice", **kwargs):
        # Vendor bills post through a journal with Latam documents, which
        # refuses posting without a document number. The collector never
        # reads it (that is ATS territory); the per-test counter only keeps
        # the numbers unique inside each test.
        self._purchase_sequence = getattr(self, "_purchase_sequence", 0) + 1
        move = self.env["account.move"].create(
            {
                "move_type": move_type,
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
                            "price_unit": price,
                            "account_id": self.expense_account.id,
                            "tax_ids": [(6, 0, [tax.id])],
                        },
                    )
                ],
                **kwargs,
            }
        )
        common.set_tax_support(move)
        move.action_post()
        return move

    def _collect(self):
        return self.collector._l10n_ec_104_collect_compras(
            self.company, PERIOD_START, PERIOD_FINISH
        )

    def test_standard_rate_purchase(self):
        self._post_purchase(100.0, self.tax_15)
        boxes = self._collect()
        self.assertEqual(boxes["500"], 100.0)
        self.assertEqual(boxes["510"], 100.0)
        self.assertEqual(boxes["520"], 15.0)
        self.assertEqual(boxes["509"], 100.0)
        self.assertEqual(boxes["519"], 100.0)
        self.assertEqual(boxes["529"], 15.0)
        self.assertEqual(boxes["526"], 0.0)
        self.assertEqual(boxes["527"], 0.0)

    def test_mixed_rates_purchase(self):
        self._post_purchase(200.0, self.tax_0)
        self._post_purchase(100.0, self.tax_no_credit)
        self._post_purchase(100.0, self.tax_5)
        boxes = self._collect()
        self.assertEqual(boxes["507"], 200.0)
        self.assertEqual(boxes["517"], 200.0)
        self.assertEqual(boxes["502"], 100.0)
        self.assertEqual(boxes["512"], 100.0)
        self.assertEqual(boxes["522"], 15.0)
        self.assertEqual(boxes["540"], 100.0)
        self.assertEqual(boxes["550"], 100.0)
        self.assertEqual(boxes["560"], 5.0)
        self.assertEqual(boxes["509"], 400.0)
        self.assertEqual(boxes["519"], 400.0)
        self.assertEqual(boxes["529"], 20.0)

    def test_same_rate_vendor_credit_note_reduces_net(self):
        bill = self._post_purchase(100.0, self.tax_15)
        self._post_purchase(
            40.0,
            self.tax_15,
            move_type="in_refund",
            reversed_entry_id=bill.id,
        )
        boxes = self._collect()
        self.assertEqual(boxes["500"], 100.0)
        self.assertEqual(boxes["510"], 60.0)
        self.assertEqual(boxes["520"], 9.0)
        self.assertEqual(boxes["526"], 0.0)
        self.assertEqual(boxes["527"], 0.0)
        self.assertEqual(boxes["529"], 9.0)

    def test_different_rate_vendor_credit_note_adjusts_positive(self):
        bill = self._post_purchase(100.0, self.tax_15)
        self._post_purchase(
            100.0,
            self.tax_12,
            move_type="in_refund",
            reversed_entry_id=bill.id,
        )
        boxes = self._collect()
        # 15.0 claimed, 12.0 reversed at the lower rate.
        self.assertEqual(boxes["520"], 3.0)
        # Absolute difference booked as positive credit adjustment (526).
        self.assertEqual(boxes["526"], 3.0)
        self.assertEqual(boxes["527"], 0.0)
        self.assertEqual(boxes["529"], 6.0)
