from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    l10n_ec_property_account_discount_id = fields.Many2one(
        "account.account",
        "C.C. Discount",
    )
    l10n_ec_property_account_return_id = fields.Many2one(
        "account.account",
        "C.C. Refund",
    )
