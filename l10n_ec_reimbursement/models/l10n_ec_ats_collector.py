"""Carry the reimbursement base total into the ATS ``compras`` row.

The key is added only when the move holds reimbursement legs, so rows for
ordinary documents stay byte-identical to the base collector's: emission
without legs never sees the key. The move's own base buckets are untouched,
mirroring Frappe's ``collect_purchase``.
"""

from odoo import api, models


class L10nEcAtsCollector(models.AbstractModel):
    _inherit = "l10n.ec.ats.collector"

    @api.model
    def _l10n_ec_compras_amounts(self, move):
        values = super()._l10n_ec_compras_amounts(move)
        details = move.reimbursement_ids
        if details:
            values["totbasesImpReemb"] = sum(details.mapped("base_amount"))
        return values
