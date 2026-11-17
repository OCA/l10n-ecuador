from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    l10n_ec_parish_id = fields.Many2one(
        "l10n.ec.parish",
        ondelete="restrict",
        string="Parish",
    )
