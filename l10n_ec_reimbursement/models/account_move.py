"""Carry the reimbursed voucher legs on the purchase-side documents.

No menus are added: the intermediary records the third-party vouchers on the
vendor bill or the purchase liquidation itself, and the legs travel from here
to the EDI values and to the ATS collector.
"""

from odoo import fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    reimbursement_ids = fields.One2many(
        comodel_name="l10n.ec.reimbursement.detail",
        inverse_name="move_id",
        string="Reimbursed Vouchers",
        help="Third-party vouchers paid by the intermediary and re-invoiced "
        "on this document (SRI reembolso).",
    )
