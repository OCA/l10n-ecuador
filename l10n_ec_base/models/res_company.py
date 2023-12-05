from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    l10n_ec_business_name = fields.Char(
        related="partner_id.l10n_ec_business_name",
        readonly=False,
    )
    l10n_ec_regimen = fields.Selection(
        string="Regimen",
        selection=[
            ("rimpe", "CONTRIBUYENTE RÉGIMEN RIMPE"),
            ("rimpe_popular", "CONTRIBUYENTE NEGOCIO POPULAR - RÉGIMEN RIMPE"),
        ],
    )

    l10n_ec_retention_agent = fields.Char(
        "Retention Agent Nro",
    )
    property_account_position_id = fields.Many2one(
        "account.fiscal.position",
        "Fiscal Position",
        related="partner_id.property_account_position_id",
        readonly=False,
    )

    def l10n_ec_get_regimen(self):
        return (
            dict(self._fields["l10n_ec_regimen"].selection).get(self.l10n_ec_regimen)
            or ""
        )
