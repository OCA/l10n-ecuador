from odoo.exceptions import ValidationError
from odoo.tests import common
from odoo.tests.common import Form


class TestModelA(common.TransactionCase):
    def test_valid_l10n_ec_entity(self):
        self.env.user.company_id = self.env.ref("l10n_ec.demo_company_ec")
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
        self.env.user.company_id = self.env.ref("l10n_ec.demo_company_ec")
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
