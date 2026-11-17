from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    l10n_ec_import_fodinfa_rate = fields.Float(
        string="FODINFA (%)",
        default=0.5,
        digits=(16, 4),
        help="FODINFA rate applied on the CIF value of imports.",
    )
    l10n_ec_import_vat_rate = fields.Float(
        string="IVA on Imports (%)",
        default=15.0,
        digits=(16, 4),
    )
    l10n_ec_customs_partner_id = fields.Many2one(
        "res.partner",
        string="Customs Authority",
        help="Partner used on the customs bill (e.g. SENAE).",
    )
    l10n_ec_import_vat_account_id = fields.Many2one(
        "account.account",
        string="IVA on Imports Account",
        check_company=True,
        help="Account debited by the IVA line of the customs bill (tax credit).",
    )
    l10n_ec_import_journal_id = fields.Many2one(
        "account.journal",
        string="Customs Bill Journal",
        check_company=True,
        domain="[('type', '=', 'purchase')]",
    )
