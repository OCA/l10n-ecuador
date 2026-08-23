from odoo import api, fields, models
from odoo.exceptions import UserError


class ResPartner(models.Model):
    _inherit = "res.partner"

    l10n_ec_business_name = fields.Char(
        "Business Name",
    )

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
