from odoo import api, models


class AccountMoveSend(models.AbstractModel):
    _inherit = "account.move.send"

    @api.model
    def _get_move_constraints(self, move):
        constraints = super()._get_move_constraints(move)
        if move._is_l10n_ec_is_purchase_liquidation():
            constraints.pop("not_sale_document", None)
        return constraints
