from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class AccountJournal(models.Model):
    _inherit = "account.journal"

    l10n_ec_sri_payment_id = fields.Many2one(
        "l10n_ec.sri.payment",
        "SRI Payment Method",
    )
    l10n_ec_is_purchase_liquidation = fields.Boolean(string="Is Purchase Liquidations?")

    @api.constrains("l10n_ec_entity", "l10n_ec_emission")
    def _constrains_l10n_ec_entity_emission(self):
        for rec in self:
            if rec.l10n_ec_entity:
                if len(rec.l10n_ec_entity) < 3 or not rec.l10n_ec_entity.isnumeric():
                    raise ValidationError(
                        _(
                            "Length less than 3 numbers or The point of entity "
                            "must contain only numbers"
                        )
                    )

            if rec.l10n_ec_emission:
                if (
                    len(rec.l10n_ec_emission) < 3
                    or not rec.l10n_ec_emission.isnumeric()
                ):
                    raise ValidationError(
                        _(
                            "Length less than 3 numbers or The point of "
                            "emission must contain only numbers"
                        )
                    )

    @api.depends("type", "l10n_latam_use_documents", "l10n_ec_is_purchase_liquidation")
    def _compute_l10n_ec_require_emission(self):
        super()._compute_l10n_ec_require_emission()
        # add support to purchase liquidation to show agency and printer point
        for journal in self.filtered(lambda j: j.country_code == "EC"):
            if journal.l10n_ec_is_purchase_liquidation:
                journal.l10n_ec_require_emission = True
