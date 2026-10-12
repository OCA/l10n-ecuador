import csv
import io
from datetime import date

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon

PERIOD_START = date(2026, 8, 1)
PERIOD_FINISH = date(2026, 8, 31)


@tagged("post_install", "-at_install")
class TestL10nEc104Wizard(AccountTestInvoicingCommon):
    """The wizard composes the three collectors and offers the CSV.

    Refusals aggregate into one ``UserError`` and produce no file: a
    non-Ecuadorian company is the one refusal the skeleton already proves.
    """

    @classmethod
    @AccountTestInvoicingCommon.setup_country("ec")
    @AccountTestInvoicingCommon.setup_chart_template("ec")
    def setUpClass(cls):
        super().setUpClass()
        chart = cls.env["account.chart.template"].with_company(cls.company)
        cls.tax_15 = chart.ref("tax_vat_15_411_goods")
        move = cls.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "company_id": cls.company.id,
                "partner_id": cls.partner_a.id,
                "invoice_date": PERIOD_START.isoformat(),
                "date": PERIOD_START.isoformat(),
                "journal_id": cls.company_data["default_journal_sale"].id,
                "invoice_line_ids": [
                    (
                        0,
                        0,
                        {
                            "name": "test line",
                            "quantity": 1.0,
                            "price_unit": 100.0,
                            "account_id": (
                                cls.company_data["default_account_revenue"].id
                            ),
                            "tax_ids": [(6, 0, [cls.tax_15.id])],
                        },
                    )
                ],
            }
        )
        move.action_post()

    def _generate(self, **values):
        wizard = self.env["l10n.ec.104.generate"].create(
            {
                "company_id": self.company.id,
                "anio": 2026,
                "mes": 8,
                **values,
            }
        )
        action = wizard.generate()
        attachment = self.env["ir.attachment"].search(
            [
                ("res_model", "=", "l10n.ec.104.generate"),
                ("res_id", "=", wizard.id),
            ]
        )
        return wizard, action, attachment

    def _csv_boxes(self, attachment):
        attachment.ensure_one()
        rows = list(csv.DictReader(io.StringIO(attachment.raw.decode("utf-8"))))
        return {row["casillero"]: float(row["valor"]) for row in rows}

    def test_generate_offers_csv_download(self):
        wizard, action, attachment = self._generate()
        self.assertEqual(action["type"], "ir.actions.act_url")
        self.assertIn(f"/web/content/{attachment.id}", action["url"])
        self.assertTrue(attachment.name.startswith("formulario_104_202608"))
        boxes = self._csv_boxes(attachment)
        self.assertEqual(boxes["401"], 100.0)
        self.assertEqual(boxes["421"], 15.0)
        self.assertEqual(boxes["429"], 15.0)
        self.assertEqual(boxes["859"], 15.0)
        self.assertIn("429: 15.0", wizard.boxes_preview)

    def test_carryover_flows_into_settlement(self):
        wizard, _action, attachment = self._generate(carryover_483=5.0)
        boxes = self._csv_boxes(attachment)
        self.assertEqual(boxes["483"], 5.0)
        self.assertEqual(boxes["499"], 20.0)
        self.assertEqual(boxes["601"], 20.0)

    def test_foreign_company_refused_without_file(self):
        foreign = self.env["res.company"].create({"name": "Foreign Co"})
        wizard = self.env["l10n.ec.104.generate"].create(
            {"company_id": foreign.id, "anio": 2026, "mes": 8}
        )
        with self.assertRaises(UserError):
            wizard.generate()
        self.assertFalse(
            self.env["ir.attachment"].search(
                [
                    ("res_model", "=", "l10n.ec.104.generate"),
                    ("res_id", "=", wizard.id),
                ]
            )
        )
