from odoo.tests import common
from odoo.tests.common import Form


class TestAccountJournal(common.TransactionCase):
    def test_l10n_ec_withholding(self):
        self.env.user.company_id = self.env.ref("l10n_ec.demo_company_ec")
        journal_form = Form(self.env["account.journal"])
        journal_form.name = "Purchase Withholding"
        journal_form.code = "PUR-WH"
        journal_form.type = "general"
        journal_form.l10n_ec_withholding_type = "purchase"
        journal_form.l10n_ec_entity = "001"
        journal_form.l10n_ec_emission = "001"
        journal_form.l10n_ec_emission_address_id = self.env.company.partner_id
        self.assertTrue(journal_form.l10n_ec_require_emission)
        self.assertTrue(journal_form.l10n_latam_use_documents)
        journal_form.l10n_ec_withholding_type = "sale"
        self.assertFalse(journal_form.l10n_ec_require_emission)
        self.assertFalse(journal_form.l10n_latam_use_documents)
        journal_form.type = "purchase"
        self.assertFalse(journal_form.l10n_ec_withholding_type)
