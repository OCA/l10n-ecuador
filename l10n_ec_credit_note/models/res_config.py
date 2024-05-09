from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    l10n_ec_property_account_discount_id = fields.Many2one(
        "account.account",
        "C.C. Discount",
        related="company_id.l10n_ec_property_account_discount_id",
        readonly=False,
    )
    l10n_ec_property_account_return_id = fields.Many2one(
        "account.account",
        related="company_id.l10n_ec_property_account_return_id",
        readonly=False,
    )
