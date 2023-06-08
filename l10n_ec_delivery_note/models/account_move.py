from odoo import fields, models


class AccountMove(models.Model):

    _inherit = "account.move"

    l10n_ec_delivery_note_ids = fields.One2many(
        comodel_name="l10n_ec.delivery.note",
        inverse_name="invoice_id",
        string="Delivery Notes",
    )
