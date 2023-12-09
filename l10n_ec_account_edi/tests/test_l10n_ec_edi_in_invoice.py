from odoo.exceptions import UserError
from odoo.tests import tagged

from .test_common import TestL10nECCommon


@tagged("post_install_l10n", "post_install", "-at_install")
class TestL10nEcInInvoice(TestL10nECCommon):
    def test_l10n_ec_in_invoice_authorization(self):
        invoice = self._l10n_ec_create_in_invoice(auto_post=True)
        with self.assertRaisesRegex(
            UserError, "Invalid provider authorization number, must be numeric only"
        ):
            invoice.l10n_ec_electronic_authorization = "must_be_only_numeric"
