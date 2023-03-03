from odoo import _, api, fields, models
from odoo.exceptions import UserError


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

    def write(self, values):
        for partner in self:
            if (
                partner.vat in ["9999999999", "9999999999999"]
                and not self.env.is_system()
                and (
                    "name" in values
                    or "vat" in values
                    or "active" in values
                    or "country_id" in values
                )
            ):
                raise UserError(_("You cannot modify record of final consumer"))
        return super(ResPartner, self).write(values)

    def unlink(self):
        for partner in self:
            if partner.vat in ["9999999999", "9999999999999"]:
                raise UserError(_("You cannot unlink final consumer"))
        return super(ResPartner, self).unlink()
