from odoo import api, models


class AccountMoveSend(models.AbstractModel):
    _inherit = "account.move.send"

    @api.model
    def _check_move_constrains(self, moves):
        if any(m._is_l10n_ec_is_purchase_liquidation() for m in moves):
            return

        super()._check_move_constrains(moves)
