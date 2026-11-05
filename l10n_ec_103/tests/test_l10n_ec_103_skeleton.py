from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestL10nEc103Skeleton(TransactionCase):
    def test_wizard_model_installed(self):
        wizard = self.env["l10n.ec.103.generate"].create(
            {"company_id": self.env.company.id, "anio": 2026, "mes": 8}
        )
        self.assertEqual(wizard.mes, 8)

    def test_generate_refuses_before_collectors(self):
        wizard = self.env["l10n.ec.103.generate"].create(
            {"company_id": self.env.company.id, "anio": 2026, "mes": 8}
        )
        with self.assertRaises(UserError):
            wizard.generate()

    def test_impossible_period_refused(self):
        with self.assertRaises(ValidationError):
            self.env["l10n.ec.103.generate"].create(
                {"company_id": self.env.company.id, "anio": 1999, "mes": 8}
            )
        with self.assertRaises(ValidationError):
            self.env["l10n.ec.103.generate"].create(
                {"company_id": self.env.company.id, "anio": 2026, "mes": 13}
            )
