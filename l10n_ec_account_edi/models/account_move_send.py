from odoo import api, models


class AccountMoveSend(models.AbstractModel):
    _inherit = "account.move.send"

    @api.model
    def _get_move_constraints(self, move):
        constraints = super()._get_move_constraints(move)
        # Ecuadorian purchase liquidations must be emailed to the supplier with
        # the SRI-authorized XML attached, which core 19.0 blocks by rejecting
        # every non-sale document here. Relax it only for moves this module has
        # actually authorized, so ordinary purchase invoices keep the core
        # restriction.
        if move.l10n_ec_authorization_date:
            constraints.pop("not_sale_document", None)
        return constraints
