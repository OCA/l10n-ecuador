from odoo import api, fields, models


class AccountJournal(models.Model):
    _inherit = "account.journal"

    l10n_ec_withholding_type = fields.Selection(
        [
            ("purchase", "Purchase"),
            ("sale", "Sale"),
        ],
        string="Withholding Type",
    )

    @api.onchange("type")
    def _onchange_type(self):
        super()._onchange_type()
        if self.type != "general":
            self.l10n_ec_withholding_type = False

    @api.depends(
        "type",
        "l10n_latam_use_documents",
        "l10n_ec_is_purchase_liquidation",
        "l10n_ec_withholding_type",
    )
    def _compute_l10n_ec_require_emission(self):
        super()._compute_l10n_ec_require_emission()
        # add support to purchase withholding to show agency and printer point
        for journal in self.filtered(lambda j: j.country_code == "EC"):
            if journal.l10n_ec_withholding_type == "purchase":
                journal.l10n_ec_require_emission = True

    @api.depends(
        "type",
        "company_id",
        "company_id.account_fiscal_country_id",
        "l10n_ec_withholding_type",
    )
    def _compute_compatible_edi_ids(self):
        # add l10n_ec_withholding_type to depends
        return super()._compute_compatible_edi_ids()

    @api.depends(
        "type",
        "company_id",
        "company_id.account_fiscal_country_id",
        "l10n_ec_withholding_type",
    )
    def _compute_edi_format_ids(self):
        # add l10n_ec_withholding_type to depends
        return super()._compute_edi_format_ids()
