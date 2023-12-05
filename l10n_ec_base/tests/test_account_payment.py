from odoo.tests import tagged
from odoo.tests.common import Form

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestAccountPayment(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls, chart_template_ref=None):
        chart_template_ref = "ec"
        super().setUpClass(chart_template_ref=chart_template_ref)
        cls.env.company.country_id = cls.env.ref("base.ec")

    def test_payment_journal(self):
        default_sri_payment = self.env.ref("l10n_ec.P1")
        bank_journal = self.company_data["default_journal_bank"]
        pay_form = Form(
            self.env["account.payment"].with_context(
                default_journal_id=bank_journal.id, default_partner_type="customer"
            )
        )
        pay_form.amount = 50.0
        pay_form.payment_type = "inbound"
        pay_form.partner_id = self.partner_a
        self.assertFalse(pay_form.l10n_ec_sri_payment_id)
        bank_journal.l10n_ec_sri_payment_id = default_sri_payment
        pay_form.journal_id = bank_journal
        payment = pay_form.save()
        self.assertEqual(payment.l10n_ec_sri_payment_id, default_sri_payment)
