from odoo import fields, models


class AccountTaxGroup(models.Model):
    _inherit = "account.tax.group"

    l10n_ec_xml_fe_code = fields.Char("Tax Code for Electronic Documents", size=5)


class AccountTax(models.Model):
    _inherit = "account.tax"

    l10n_ec_xml_fe_code = fields.Char(
        "Tax Code for Electronic Documents",
        size=10,
        help="Tax Code used into xml files for electronic documents sent to S.R.I., "
        "If field is empty, description field are used instead",
    )


class AccountTaxTemplate(models.Model):
    _inherit = "account.tax.template"

    l10n_ec_xml_fe_code = fields.Char(
        "Tax Code for Electronic Documents",
        size=10,
        help="Tax Code used into xml files for electronic documents sent to S.R.I., "
        "If field is empty, description field are used instead",
    )

    def _l10n_ec_get_tax_vals(self):
        # funcion generica para devolver datos adicionales de impuestos
        # para ser llamada al momento de cargar el plan contable
        # o desde la instalacion del modulo(se ejecuta desde un post_init)
        return {"l10n_ec_xml_fe_code": self.l10n_ec_xml_fe_code}

    def _get_tax_vals(self, company, tax_template_to_tax):
        """This method generates a dictionnary of all the values for the tax that
        will be created."""
        self.ensure_one()
        val = super(AccountTaxTemplate, self)._get_tax_vals(
            company, tax_template_to_tax
        )
        val.update(self._l10n_ec_get_tax_vals())
        return val
