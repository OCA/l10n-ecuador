from datetime import date

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.l10n_ec_account_edi.tests.test_edi_common import (
    TestL10nECEdiCommon,
)

PERIOD_START = date(2026, 8, 1)
PERIOD_FINISH = date(2026, 8, 31)


@tagged("post_install", "-at_install")
class TestL10nEc104AtsReconcile(TestL10nECEdiCommon):
    """The 104 and the ATS read the same moves and must agree.

    Check A compares net with net (ATS establishment totals vs the 104's
    419); check B compares gross with gross (ATS VAT amounts vs the 104's
    429 rebuilt with twice the credit-note tax). A direct 429-vs-totalVentas
    comparison would drift by twice the notes -- that is the trap this
    module exists for, so the Bride test with a credit note pins the
    adjustment instead of the naive equality.
    """

    @classmethod
    @AccountTestInvoicingCommon.setup_country("ec")
    @AccountTestInvoicingCommon.setup_chart_template("ec")
    def setUpClass(cls):
        super().setUpClass()
        cls()._setup_edi_company_ec()
        cls.reconcile = cls.env["l10n.ec.104.ats.reconciler"]
        chart = cls.env["account.chart.template"].with_company(cls.company)
        cls.tax_15 = chart.ref("tax_vat_15_411_goods")
        cls.journal_sale = cls.company_data["default_journal_sale"]
        cls.journal_sale.write(
            {
                "l10n_ec_emission_address_id": cls.partner_contact.id,
                "l10n_ec_sri_payment_id": cls.env.ref("l10n_ec.P1").id,
                "l10n_latam_use_documents": True,
                "l10n_ec_entity": "001",
                "l10n_ec_emission": "001",
            }
        )
        cls.client = cls.env["res.partner"].create(
            {
                "name": "Cliente RUC",
                "vat": "1713109678001",
                "l10n_latam_identification_type_id": (cls.env.ref("l10n_ec.ec_ruc").id),
                "country_id": cls.env.ref("base.ec").id,
            }
        )

    def _post_ats_sale(self, price, journal=None, posting_date=PERIOD_START):
        self._document_sequence = getattr(self, "_document_sequence", 0) + 1
        move = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "company_id": self.company.id,
                "partner_id": self.client.id,
                "journal_id": (journal or self.journal_sale).id,
                "l10n_latam_document_type_id": (self.env.ref("l10n_ec.ec_dt_01").id),
                "l10n_latam_document_number": (
                    f"001-001-{self._document_sequence:09d}"
                ),
                "l10n_ec_sri_payment_id": self.env.ref("l10n_ec.P1").id,
                "invoice_date": posting_date.isoformat(),
                "date": posting_date.isoformat(),
                "invoice_line_ids": [
                    (
                        0,
                        0,
                        {
                            "name": "test line",
                            "quantity": 1.0,
                            "price_unit": price,
                            "account_id": (
                                self.company_data["default_account_revenue"].id
                            ),
                            "tax_ids": [(6, 0, [self.tax_15.id])],
                        },
                    )
                ],
            }
        )
        move.action_post()
        return move

    def _post_ats_credit_note(self, invoice, price=None):
        self._document_sequence = getattr(self, "_document_sequence", 0) + 1
        reversal = invoice._reverse_moves(
            [
                {
                    "date": PERIOD_START.isoformat(),
                    "invoice_date": PERIOD_START.isoformat(),
                    "l10n_latam_document_type_id": self.env.ref("l10n_ec.ec_dt_04").id,
                    "l10n_latam_document_number": (
                        f"001-001-{self._document_sequence:09d}"
                    ),
                }
            ]
        )
        if price is not None:
            reversal.invoice_line_ids.write({"price_unit": price})
        reversal.action_post()
        return reversal

    def _check(self):
        return self.reconcile.check_period(self.company, PERIOD_START, PERIOD_FINISH)

    def test_match_without_credit_notes(self):
        self._post_ats_sale(100.0)
        result = self._check()
        self.assertTrue(result["match"])
        by_check = {c["check"]: c for c in result["checks"]}
        self.assertEqual(by_check["A"]["ats"], 100.0)
        self.assertEqual(by_check["A"]["form_104"], 100.0)
        self.assertEqual(by_check["B"]["ats"], 15.0)
        self.assertEqual(by_check["B"]["form_104"], 15.0)

    def test_match_with_credit_note(self):
        invoice = self._post_ats_sale(100.0)
        self._post_ats_credit_note(invoice, price=40.0)
        result = self._check()
        by_check = {c["check"]: c for c in result["checks"]}
        # Net on both sides: 100 − 40.
        self.assertEqual(by_check["A"]["ats"], 60.0)
        self.assertEqual(by_check["A"]["form_104"], 60.0)
        # Gross on both sides: 15 + 6 vs 9 + 2 × 6.
        self.assertEqual(by_check["B"]["ats"], 21.0)
        self.assertEqual(by_check["B"]["form_104"], 21.0)
        self.assertTrue(result["match"])

    def test_ats_refusal_propagates(self):
        move = self._post_ats_sale(100.0)
        move.partner_id.write({"vat": False})
        with self.assertRaises(UserError):
            self._check()

    def test_empty_period_matches(self):
        result = self._check()
        self.assertTrue(result["match"])
        self.assertEqual(
            [(c["ats"], c["form_104"]) for c in result["checks"]],
            [(0.0, 0.0), (0.0, 0.0)],
        )

    def test_wizard_download(self):
        self._post_ats_sale(100.0)
        wizard = self.env["l10n.ec.104.ats.reconcile"].create(
            {"company_id": self.company.id, "anio": 2026, "mes": 8}
        )
        action = wizard.generate()
        self.assertEqual(action["type"], "ir.actions.act_url")
        attachment = self.env["ir.attachment"].search(
            [
                ("res_model", "=", "l10n.ec.104.ats.reconcile"),
                ("res_id", "=", wizard.id),
            ]
        )
        self.assertTrue(attachment.name.startswith("conciliacion_104_ats_202608"))
        self.assertIn("A: ATS 100.0 vs 104 100.0", wizard.result_preview)
        self.assertIn("MATCH", wizard.result_preview)
