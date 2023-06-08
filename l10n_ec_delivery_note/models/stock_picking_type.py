from odoo import fields, models


class StockPickingType(models.Model):
    _inherit = "stock.picking.type"

    l10n_ec_default_delivery_note = fields.Boolean(
        string="Create Delivery Note by default?"
    )
