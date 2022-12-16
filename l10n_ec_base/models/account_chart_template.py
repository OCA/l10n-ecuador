from odoo import _, api, models


class AccountChartTemplate(models.Model):
    _inherit = "account.chart.template"

    def _load(self, sale_tax_rate, purchase_tax_rate, company):
        """Set tax calculation rounding method required in Ecuadorian localization"""
        res = super()._load(sale_tax_rate, purchase_tax_rate, company)
        if company.country_id.code == "EC":
            company.write({"tax_calculation_rounding_method": "round_globally"})
        return res

    @api.model
    def _10n_ec_post_init(self):
        """ "
        Parametrizaciones iniciales en compañias ecuatorianas
        Esto cuando se instale el modulo la primera vez
        ya que no se puede cargar junto con el plan contable de l10n_ec
        """
        l10n_ec_ifrs = self.env.ref("l10n_ec.l10n_ec_ifrs")
        all_companies = self.env["res.company"].search(
            [("chart_template_id", "=", l10n_ec_ifrs.id)]
        )
        all_companies.write({"tax_calculation_rounding_method": "round_globally"})
        for company in all_companies:
            # actualizar el codigo de impuesto para facturacion electronica
            template_xmlids = (
                company.chart_template_id.tax_template_ids.get_external_id()
            )
            for tax_template in company.chart_template_id.tax_template_ids:
                module, name = template_xmlids[tax_template.id].split(".", 1)
                xml_id = "%s.%s_%s" % (module, company.id, name)
                tax = self.env.ref(xml_id, False)
                if tax:
                    tax.write(tax_template._l10n_ec_get_tax_vals())
            # crear los diarios
            self.env["account.journal"].create(
                self._l10n_ec_prepare_all_journals(company)
            )
        return True

    def _prepare_all_journals(self, acc_template_ref, company, journals_dict=None):
        journal_data = super()._prepare_all_journals(
            acc_template_ref, company, journals_dict
        )
        journal_data.extend(self._l10n_ec_prepare_all_journals(company))
        return journal_data

    def _l10n_ec_prepare_all_journals(self, company):
        journals = []
        if company.country_id.code == "EC":
            journals = [
                {
                    "name": _("Liquidation of Purchases"),
                    "type": "purchase",
                    "code": _("LDP"),
                    "show_on_dashboard": True,
                    "color": 11,
                    "sequence": 14,
                    "l10n_latam_use_documents": True,
                    "company_id": company.id,
                },
            ]
        return journals
