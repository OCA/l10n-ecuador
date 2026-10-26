from odoo import fields, models


class AccountInvoiceRefund(models.TransientModel):
    _inherit = "account.move.reversal"

    l10n_ec_type_credit_note = fields.Selection(
        [("discount", "Discount"), ("return", "Return")], string="Credit Note type"
    )

    def _prepare_default_reversal(self, move):
        move_vals = super()._prepare_default_reversal(move)
        if self.company_id.account_fiscal_country_id.code == "EC":
            move_vals.update(
                {
                    "l10n_ec_type_credit_note": self.l10n_ec_type_credit_note,
                }
            )
        return move_vals
