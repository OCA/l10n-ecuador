from odoo import api, fields, models
from odoo.exceptions import UserError


class ResPartner(models.Model):
    _inherit = "res.partner"

    l10n_ec_business_name = fields.Char(
        "Business Name",
    )

    # No valida RUCs Sociedades Juridicas (S.A.S.) ej: 1793189549001
    def _check_vat(self, validation="error"):
        partner_to_skip_validate = self.env["res.partner"]
        for partner in self:
            if (
                partner.country_id.code == "EC"
                and partner.vat
                and len(partner.vat) == 13
                and partner.vat[2] == "9"
            ):
                partner_to_skip_validate |= partner
        return super(ResPartner, self - partner_to_skip_validate)._check_vat(
            validation=validation
        )

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
                raise UserError(
                    self.env._("You cannot modify record of final consumer")
                )
        return super().write(values)

    @api.ondelete(at_uninstall=False)
    def _unlink_prevent_final_consumer(self):
        for partner in self:
            if partner.vat in ["9999999999", "9999999999999"]:
                raise UserError(self.env._("You cannot unlink final consumer"))
