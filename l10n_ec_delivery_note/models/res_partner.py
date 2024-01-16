from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    l10n_ec_is_carrier = fields.Boolean("Is Carrier?")
    l10n_ec_car_plate = fields.Char("Car plate", size=8)
