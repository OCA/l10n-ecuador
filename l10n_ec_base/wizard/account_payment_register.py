from odoo import api, fields, models


class AccountPaymentRegister(models.TransientModel):
    _inherit = "account.payment.register"

    l10n_ec_sri_payment_id = fields.Many2one(
        "l10n_ec.sri.payment", "SRI Payment Method", required=False
    )

    @api.onchange("journal_id")
    def _onchange_journal(self):
        if self.journal_id and self.journal_id.l10n_ec_sri_payment_id:
            self.l10n_ec_sri_payment_id = self.journal_id.l10n_ec_sri_payment_id.id

    def _create_payment_vals_from_wizard(self, batch_result):
        res = super()._create_payment_vals_from_wizard(batch_result)
        res.update({"l10n_ec_sri_payment_id": self.l10n_ec_sri_payment_id.id})
        return res
