from odoo import fields, models


class AccountPaymentTerm(models.Model):
    _inherit = "account.payment.term"

    l10n_ec_sri_type = fields.Selection(
        [
            ("cash", "Cash"),
            ("credit", "Credit"),
        ],
        string="SRI Type",
        default="credit",
        required=True,
    )
