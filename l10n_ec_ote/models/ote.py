from odoo import fields, models


class City(models.Model):
    _name = "l10n_ec_ote.canton"
    _description = "City"

    state_id = fields.Many2one(
        "res.country.state",
        ondelete="restrict",
    )
    name = fields.Char()
    code = fields.Char()


class Parish(models.Model):
    _name = "l10n_ec_ote.parish"
    _description = "Parish"

    canton_id = fields.Many2one(
        "l10n_ec_ote.canton",
        ondelete="restrict",
    )
    name = fields.Char()
    code = fields.Char()
