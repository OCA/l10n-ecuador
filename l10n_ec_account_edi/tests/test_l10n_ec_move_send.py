from odoo.tests import tagged

from .sri_response import patch_service_sri
from .test_edi_common import TestL10nECEdiCommon

FORM_ID = "l10n_ec_account_edi.account_invoice_liquidation_purchase_form_view"


@tagged("post_install_l10n", "post_install", "-at_install")
class TestL10nEcMoveSend(TestL10nECEdiCommon):
    """Core 19.0 refuses to send any non-sale document through
    ``account.move.send``. SRI requires the seller to email the purchase
    liquidation to the supplier with the authorized XML attached, so the
    ``not_sale_document`` constraint has to be dropped for authorized
    liquidations only.
    """

    def _create_purchase_liquidation(self, auto_post=False):
        """Purchase liquidation built with the module's own liquidation form."""
        form = self._l10n_ec_create_form_move(
            move_type="in_invoice",
            internal_type="purchase_liquidation",
            partner=self.partner_dni,
            latam_document_type=self.env.ref("l10n_ec.ec_dt_03"),
            use_payment_term=False,
            form_id=FORM_ID,
        )
        liquidation = form.save()
        if auto_post:
            liquidation.action_post()
        return liquidation

    def test_purchase_liquidation_not_authorized_keeps_constraint(self):
        """Without an SRI authorization date the core restriction still applies."""
        self._setup_edi_company_ec()
        liquidation = self._create_purchase_liquidation(auto_post=True)
        self.assertEqual(liquidation.move_type, "in_invoice")
        self.assertFalse(liquidation.l10n_ec_authorization_date)
        constraints = self.env["account.move.send"]._get_move_constraints(liquidation)
        self.assertNotIn("not_posted", constraints)
        self.assertIn("not_sale_document", constraints)

    @patch_service_sri
    def test_purchase_liquidation_authorized_drops_constraint(self):
        """An SRI-authorized liquidation is no longer rejected as a non-sale
        document, which is what the cron in account_edi_document.py relies on.
        """
        self._setup_edi_company_ec()
        self._l10n_ec_edi_company_no_account()
        liquidation = self._create_purchase_liquidation(auto_post=True)
        self.generate_payment(invoice_ids=liquidation.ids, journal=self.journal_cash)
        edi_doc = liquidation._get_edi_document(self.edi_format)
        edi_doc._process_documents_web_services(with_commit=False)
        # The authorization date is computed from the SRI EDI document, so this
        # asserts the module really authorized the liquidation over its own
        # (mocked) SRI channel rather than the field being forced by hand.
        self.assertEqual(
            liquidation.l10n_ec_authorization_date,
            edi_doc.l10n_ec_authorization_date,
        )
        self.assertTrue(liquidation.l10n_ec_authorization_date)
        constraints = self.env["account.move.send"]._get_move_constraints(liquidation)
        self.assertNotIn("not_posted", constraints)
        self.assertNotIn("not_sale_document", constraints)
