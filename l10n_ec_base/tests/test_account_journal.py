from odoo.exceptions import ValidationError
from odoo.tests import Form, common


class TestModelA(common.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ec_country = cls.env.ref("base.ec")
        cls.company_ec = cls.env["res.company"].create(
            {"name": "EC Company", "country_id": ec_country.id}
        )
        cls.env.user.company_ids |= cls.company_ec
        cls.env.user.company_id = cls.company_ec

    def test_valid_l10n_ec_entity(self):
        journal_form = Form(self.env["account.journal"])
        journal_form.name = "nametest"
        journal_form.type = "sale"
        journal_form.l10n_latam_use_documents = True
        journal_form.code = "inv"
        journal_form.l10n_ec_entity = "001"
        journal_form.l10n_ec_emission = "001"
        journal_form.l10n_ec_emission_address_id = self.env.company.partner_id
        self.assertEqual(journal_form.name, "nametest")
        with self.assertRaises(ValidationError):
            journal_form.l10n_ec_entity = "abc"
            journal_form.save()
        journal_form.l10n_ec_entity = "001"
        with self.assertRaises(ValidationError):
            journal_form.l10n_ec_emission = "abc"
            journal_form.save()

    def test_l10n_ec_purchase_liquidation(self):
        journal_form = Form(self.env["account.journal"])
        journal_form.name = "purchase liquidation"
        journal_form.type = "purchase"
        journal_form.l10n_latam_use_documents = True
        journal_form.l10n_ec_is_purchase_liquidation = True
        journal_form.code = "PUR-LIQ"
        journal_form.l10n_ec_entity = "001"
        journal_form.l10n_ec_emission = "001"
        journal_form.l10n_ec_emission_address_id = self.env.company.partner_id
        journal = journal_form.save()
        self.assertTrue(journal.l10n_ec_require_emission)
