from odoo import fields, models


class AdditionalInformation(models.Model):
    _name = "l10n.ec.additional.information"
    _description = "Is optional for electronic documents"

    name = fields.Char(required=True)
    description = fields.Char(required=True)
    move_id = fields.Many2one("account.move", "Account Move", ondelete="cascade")
