from odoo import fields, models

from .data import TAX_SUPPORT


class ResPartner(models.Model):
    _inherit = "res.partner"

    l10n_ec_avoid_withhold = fields.Boolean(
        related="property_account_position_id.l10n_ec_avoid_withhold",
    )
    l10n_ec_tax_support = fields.Selection(
        TAX_SUPPORT, string="Tax Support", help="Tax support in invoice line"
    )
