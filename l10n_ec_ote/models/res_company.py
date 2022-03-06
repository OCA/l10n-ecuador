from odoo import api, fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    @api.onchange("canton_id")
    def _onchange_canton_id(self):
        self.city = self.canton_id.name or ""

    city_id = fields.Many2one(
        "l10n_ec_ote.canton",
        ondelete="restrict",
        string="City",
        related="partner_id.city_id",
    )

    parish_id = fields.Many2one(
        "l10n_ec_ote.parish",
        ondelete="restrict",
        string="Parish",
        related="partner_id.parish_id",
    )
