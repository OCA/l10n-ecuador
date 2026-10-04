from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    l10n_ec_avoid_withhold = fields.Boolean(
        related="property_account_position_id.l10n_ec_avoid_withhold",
    )
    l10n_ec_tax_support = fields.Char(
        string="Tax Support",
        size=2,
        help="Tax support in invoice line. A Tabla 5 code, captured as typed "
        "rather than chosen from a dropdown, so a code the SRI added after "
        "this label list was written can still be recorded. "
        "l10n_ec_ats validates it against the Tabla 5 catalog for the period "
        "being reported.",
    )
    l10n_ec_related_party = fields.Boolean(
        string="Related Party",
        help="Related party (parteRel) in the SRI withholding certificate",
    )
