from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    l10n_ec_type_environment = fields.Selection(
        related="company_id.l10n_ec_type_environment", readonly=False
    )
    l10n_ec_key_type_id = fields.Many2one(
        comodel_name="sri.key.type",
        related="company_id.l10n_ec_key_type_id",
        readonly=False,
    )
    l10n_ec_invoice_version = fields.Selection(
        related="company_id.l10n_ec_invoice_version", readonly=False
    )
    l10n_ec_liquidation_version = fields.Selection(
        related="company_id.l10n_ec_liquidation_version", readonly=False
    )
    l10n_ec_credit_note_version = fields.Selection(
        related="company_id.l10n_ec_credit_note_version", readonly=False
    )
    l10n_ec_debit_note_version = fields.Selection(
        related="company_id.l10n_ec_debit_note_version", readonly=False
    )
    l10n_ec_final_consumer_limit = fields.Float(
        string="Invoice Sales Limit Final Consumer",
        config_parameter="l10n_ec_final_consumer_limit",
        default=50.0,
        readonly=False,
    )
