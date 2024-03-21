from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    l10n_ec_delivery_note_days = fields.Integer(string="Days of transfer by default")
    # campos para emision electronica
    l10n_ec_validate_invoice_exist = fields.Boolean("Validate invoice already create?")
    l10n_ec_delivery_note_version = fields.Selection(
        [
            ("1.0.0", "1.0.0"),
            ("1.1.0", "1.1.0"),
        ],
        string="Delivery Note Version xml",
        default="1.1.0",
    )
    l10n_ec_send_mail_remission = fields.Boolean("Delivery Note?", default=True)
