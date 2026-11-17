from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    l10n_ec_parish_id = fields.Many2one(
        "l10n.ec.parish",
        ondelete="restrict",
        string="Parish",
        related="partner_id.l10n_ec_parish_id",
        readonly=False,
    )
