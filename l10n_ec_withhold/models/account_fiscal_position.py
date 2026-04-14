from odoo import fields, models


class AccountFiscalPosition(models.Model):
    _inherit = "account.fiscal.position"

    l10n_ec_avoid_withhold = fields.Boolean(
        string="Avoid Withholding?",
        help="Select if the tax position no require withholding",
    )
