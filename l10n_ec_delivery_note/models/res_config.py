from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    l10n_ec_delivery_note_days = fields.Integer(
        string="Days of transfer by default",
        related="company_id.l10n_ec_delivery_note_days",
        readonly=False,
    )
    # campos para emision electronica
    l10n_ec_validate_invoice_exist = fields.Boolean(
        related="company_id.l10n_ec_validate_invoice_exist",
        readonly=False,
    )
    l10n_ec_delivery_note_version = fields.Selection(
        related="company_id.l10n_ec_delivery_note_version", readonly=False
    )
    l10n_ec_send_mail_remission = fields.Boolean(
        "Guía de Remisión?",
        related="company_id.l10n_ec_send_mail_remission",
        readonly=False,
    )
