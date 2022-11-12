from odoo import api, fields, models


class AccountPayment(models.Model):
    _inherit = "account.payment"

    l10n_ec_sri_payment_id = fields.Many2one(
        "l10n_ec.sri.payment",
        "SRI Payment Method",
    )

    @api.onchange("journal_id")
    def _onchange_journal(self):
        res = super(AccountPayment, self)._onchange_journal()
        if self.journal_id and self.journal_id.l10n_ec_sri_payment_id:
            self.l10n_ec_sri_payment_id = self.journal_id.l10n_ec_sri_payment_id.id
        return res
