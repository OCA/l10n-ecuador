from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"
    l10n_ec_is_related = fields.Boolean(
        string="Is Related", help="Indicates if the partner is related to the company"
    )

    def is_related_partner(self):
        """
        Method to determine if the partner is related to the company.
        :return: Boolean indicating if the partner is related.
        """
        ats_srt = "SI" if self.l10n_ec_is_related else "NO"
        return ats_srt
