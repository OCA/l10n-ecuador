from dateutil.relativedelta import relativedelta

from odoo.tests import tagged

from odoo.addons.l10n_ec_account_edi.tests.test_l10n_ec_edi_liquidation import (
    TestL10nEcPurchaseLiquidation,
)
from odoo.addons.l10n_ec_withhold.tests.test_l10n_ec_purchase_withhold import (
    TestL10nPurchaseWithhold,
)
from odoo.addons.l10n_ec_withhold.tests.test_l10n_ec_sale_withhold import (
    TestL10nSaleWithhold,
)


def sri_get_name(date):
    date_end = date.replace(day=1) + relativedelta(months=1, days=-1)
    return "AT%s" % (date_end.strftime("%Y%m"))


@tagged("post_install_l10n", "post_install", "-at_install")
class TestL10nSriAts(
    TestL10nEcPurchaseLiquidation, TestL10nSaleWithhold, TestL10nPurchaseWithhold
):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def _prepare_invoice_with_withhold(self, invoice=None):
        self.WizardWithhold = self.env["l10n_ec.wizard.create.purchase.withhold"]
        if invoice is None:
            invoice = self._l10n_ec_create_in_invoice(self.partner_ruc, auto_post=True)
        wizard_form = self._prepare_new_wizard_withhold_purchase(
            invoice,
            tax_withhold_vat=self.tax_withhold_vat_100,
            tax_withhold_profit=self.tax_withhold_profit_303,
            tax_support_withhold_vat="01",
            tax_support_withhold_profit="01",
        )
        wizard = wizard_form.save()
        wizard.button_validate()
        return invoice

    def _create_data_for_ats(self):
        self._setup_edi_company_ec()
        out_invoice = [
            self.get_invoice(self.partner_dni),
            self.get_invoice(self.partner_dni),
        ]
        self.partner_ruc.property_account_position_id = self.position_require_withhold
        invoice = self._prepare_invoice_with_withhold()
        liquidation = self._l10n_ec_prepare_edi_liquidation(
            auto_post=True, partner=self.partner_ruc
        )
        liquidation = self._prepare_invoice_with_withhold(liquidation)
        in_invoices = [invoice, liquidation]
        return {"out_invoice": out_invoice, "in_invoice": in_invoices}

    def test_ats(self):
        data = self._create_data_for_ats()
        self.assertTrue(data)
        self.assertTrue(data["out_invoice"])
        self.assertTrue(data["in_invoice"])
