from odoo import api, fields, models


class AccountPayment(models.Model):
    _inherit = "account.payment"

    l10n_ec_sri_payment_id = fields.Many2one(
        "l10n_ec.sri.payment",
        "SRI Payment Method",
        compute="_compute_l10n_ec_sri_payment_id",
        store=True,
        readonly=False,
        precompute=True,
    )

    @api.depends("journal_id")
    def _compute_l10n_ec_sri_payment_id(self):
        for payment in self:
            if payment.journal_id and payment.journal_id.l10n_ec_sri_payment_id:
                payment.l10n_ec_sri_payment_id = (
                    payment.journal_id.l10n_ec_sri_payment_id.id
                )
