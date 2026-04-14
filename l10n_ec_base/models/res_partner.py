from odoo import api, fields, models
from odoo.exceptions import UserError


class ResPartner(models.Model):
    _inherit = "res.partner"

    l10n_ec_business_name = fields.Char(
        "Business Name",
    )

    # No valida RUCs Sociedades Juridicas (S.A.S.) ej: 1793189549001
    @api.constrains("vat", "country_id")
    def check_vat(self):
        partner_to_skip_validate = self.env["res.partner"]
        for partner in self:
            if (
                partner.country_id.code == "EC"
                and partner.vat
                and len(partner.vat) == 13
                and partner.vat[2] == "9"
            ):
                partner_to_skip_validate |= partner
        partners_to_validate = self - partner_to_skip_validate
        if not partners_to_validate:
            return True
        check_vat_super = getattr(
            super(ResPartner, partners_to_validate), "check_vat", None
        )
        if callable(check_vat_super):
            return check_vat_super()
        return True

    def write(self, values):
        protected_fields = {"name", "vat", "active", "country_id"}
        if protected_fields & values.keys():
            for partner in self:
                if (
                    partner.vat in ["9999999999", "9999999999999"]
                    and not partner.env.is_system()
                ):
                    raise UserError(
                        self.env._("You cannot modify record of final consumer")
                    )
        return super().write(values)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_final_consumer(self):
        for partner in self:
            if partner.vat in ["9999999999", "9999999999999"]:
                raise UserError(self.env._("You cannot unlink final consumer"))
