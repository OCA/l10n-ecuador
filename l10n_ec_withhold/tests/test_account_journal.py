from odoo.tests import Form, tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install_l10n", "post_install", "-at_install")
class TestAccountJournal(AccountTestInvoicingCommon):
    @classmethod
    @AccountTestInvoicingCommon.setup_country("ec")
    def setUpClass(cls):
        # 19.0 no longer loads ``l10n_ec.demo_company_ec``: demo data is not
        # installed by default, so the Ecuadorian company comes from the chart
        # template instead. Same shape as ``l10n_ec_base``'s own journal test.
        super().setUpClass()

    def test_l10n_ec_withholding(self):
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
