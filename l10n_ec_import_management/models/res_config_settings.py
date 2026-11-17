from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    l10n_ec_import_fodinfa_rate = fields.Float(
        related="company_id.l10n_ec_import_fodinfa_rate", readonly=False
    )
    l10n_ec_import_vat_rate = fields.Float(
        related="company_id.l10n_ec_import_vat_rate", readonly=False
    )
    l10n_ec_customs_partner_id = fields.Many2one(
        related="company_id.l10n_ec_customs_partner_id", readonly=False
    )
    l10n_ec_import_vat_account_id = fields.Many2one(
        related="company_id.l10n_ec_import_vat_account_id", readonly=False
    )
    l10n_ec_import_journal_id = fields.Many2one(
        related="company_id.l10n_ec_import_journal_id", readonly=False
    )
