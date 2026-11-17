from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    l10n_ec_tariff_id = fields.Many2one(
        "l10n_ec.import.tariff",
        string="Tariff Subheading",
        company_dependent=True,
        help="Customs tariff subheading (subpartida arancelaria) used to compute Ad Valorem.",
    )
