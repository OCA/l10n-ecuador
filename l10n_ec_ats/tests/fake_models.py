from odoo import fields, models


class L10nEcTemporalTestEntry(models.Model):
    _name = "l10n.ec.temporal.test.entry"
    _inherit = "l10n.ec.temporal"
    _description = "Ecuadorian temporal test entry"

    code = fields.Char(required=True)
