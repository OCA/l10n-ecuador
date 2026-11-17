from odoo import fields, models


class L10nEcParish(models.Model):
    _name = "l10n.ec.parish"
    _description = "Ecuadorian's Parish"

    city_id = fields.Many2one(comodel_name="res.city", string="City", required=True)
    code = fields.Char(required=True)
    name = fields.Char(required=True)
