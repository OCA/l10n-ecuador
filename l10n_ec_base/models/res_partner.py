from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    l10n_ec_business_name = fields.Char(
        "Business Name",
        required=False,
        readonly=False,
        help="",
    )

    # No valida RUCs Sociedades Juridicas (S.A.S.) ej: 1793189549001
    @api.constrains("vat", "country_id")
    def check_vat(self):
        _vat = self.vat
        if (
            self.country_id.code != "EC"
            and _vat
            and (_vat[2] != "9" or len(_vat) != 13 or _vat[-3:] == "000")
        ):
            return super(ResPartner, self).check_vat()
