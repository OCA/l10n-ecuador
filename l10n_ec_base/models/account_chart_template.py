from odoo import api, models

from odoo.addons.account.models.chart_template import template
from odoo.addons.l10n_ec_base.data.account_tax_data import TAX_DATA_EC
from odoo.addons.l10n_ec_base.data.account_tax_group_data import TAX_GROUP_DATA_EC


class AccountChartTemplate(models.AbstractModel):
    _inherit = "account.chart.template"

    def _load(self, template_code, company, install_demo):
        """Set tax calculation rounding method required in Ecuadorian localization"""
        res = super()._load(template_code, company, install_demo)
        if company.country_id.code == "EC":
            # set SRI payment for records exist
            self._l10n_ec_set_default_sri_payment(company)
        return res

    @api.model
    def _10n_ec_post_init(self):
        """ "
        Parametrizaciones iniciales en compañias ecuatorianas
        Esto cuando se instale el modulo la primera vez
        ya que no se puede cargar junto con el plan contable de l10n_ec
        """
        all_companies = self.env["res.company"].search([("chart_template", "=", "ec")])
        all_companies.write({"tax_calculation_rounding_method": "round_globally"})
        for company in all_companies:
            # set SRI payment for records exist
            self._l10n_ec_set_default_sri_payment(company)
            Template = self.with_company(company)
            Template._load_data({"account.tax": self._get_ec_new_account_tax()})
            Template._load_data({"account.tax": TAX_DATA_EC})
            Template._load_data({"account.tax.group": TAX_GROUP_DATA_EC})
            Template._load_data({"account.journal": self._get_ec_new_account_journal()})
        return True

    def _l10n_ec_set_default_sri_payment(self, company):
        default_payment = self.env.ref("l10n_ec.P1", False)
        if not default_payment:
            return False
        invoices = self.env["account.move"].search(
            [
                ("company_id", "=", company.id),
                ("l10n_ec_sri_payment_id", "=", False),
                ("move_type", "!=", "entry"),
            ]
        )
        invoices.write({"l10n_ec_sri_payment_id": default_payment.id})
        return True

    @template("ec", "res.company")
    def _get_ec_res_company_values(self):
        return {
            self.env.company.id: {
                "tax_calculation_rounding_method": "round_globally",
            },
        }

    @template("ec", "account.tax")
    def _get_ec_new_account_tax(self):
        return self._parse_csv("ec", "account.tax", module="l10n_ec_base")

    @template("ec", "account.journal")
    def _get_ec_new_account_journal(self):
        return self._parse_csv("ec", "account.journal", module="l10n_ec_base")

    @template("ec", "account.tax")
    def _get_ec_update_account_tax_data(self):
        """
        Prepare data to update records
        :return dict(tax_id_xml: dict(values to write))
        """
        return TAX_DATA_EC

    @template("ec", "account.tax.group")
    def _get_ec_update_account_tax_group_data(self):
        """
        Prepare data to update records
        :return dict(tax_group_id_xml: dict(values to write))
        """
        return TAX_GROUP_DATA_EC
