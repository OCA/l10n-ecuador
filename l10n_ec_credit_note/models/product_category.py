from odoo import fields, models


class ProductCategory(models.Model):
    _inherit = "product.category"

    # Fields for Ecuador Credit Note
    l10n_ec_property_account_discount_id = fields.Many2one(
        "account.account",
        "C.C. Discount",
        company_dependent=True,
    )
    l10n_ec_property_account_return_id = fields.Many2one(
        "account.account",
        "C.C. Refund",
        company_dependent=True,
    )
