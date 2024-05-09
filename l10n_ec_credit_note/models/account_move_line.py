from odoo import models


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    def _compute_account_id(self):
        res = super()._compute_account_id()
        for rec in self.filtered(
            lambda line: line.display_type == "product"
            and line.company_id.country_code == "EC"
            and line.move_id.move_type == "out_refund"
        ):
            new_account = rec.move_id._get_account_product_line(
                rec.product_id.id,
                rec.move_id.l10n_ec_type_credit_note,
            )
            if new_account:
                rec.account_id = new_account.id
        return res
