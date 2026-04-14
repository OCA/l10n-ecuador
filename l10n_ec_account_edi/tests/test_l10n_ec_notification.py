from odoo.tests import tagged

from .sri_response import patch_service_sri, validation_sri_response_returned
from .test_edi_common import TestL10nECEdiCommon


@tagged("post_install_l10n", "post_install", "-at_install", "notification")
class TestL10nNotification(TestL10nECEdiCommon):
    @patch_service_sri(validation_response=validation_sri_response_returned)
    def test_l10n_ec_notification_when_unauthorized_documents(self):
        """Test that the cron task is executed correctly."""
        self._setup_edi_company_ec()
        invoice = self._l10n_ec_prepare_edi_out_invoice()
        invoice.action_post()
        edi_doc = invoice._get_edi_document(self.edi_format)
        edi_doc._process_documents_web_services(with_commit=False)
        self.env["res.company"].l10n_ec_action_unauthorized_documents_notification()
        mails_to_send = self.env["mail.mail"].search_count(
            [
                ("model", "=", "res.company"),
                ("res_id", "=", self.company.id),
                ("state", "=", "outgoing"),
                ("subject", "=", "Unauthorized electronic documents"),
                ("body", "ilike", invoice.name),
            ]
        )
        self.assertEqual(mails_to_send, 1)

    @patch_service_sri
    def test_l10n_ec_notification_document_authorized(self):
        """Test that the cron task is executed correctly."""
        self._setup_edi_company_ec()
        invoice = self._l10n_ec_prepare_edi_out_invoice()
        invoice.action_post()
        edi_doc = invoice._get_edi_document(self.edi_format)
        edi_doc._process_documents_web_services(with_commit=False)
        self.env["res.company"].l10n_ec_action_unauthorized_documents_notification()
        mails_to_send = self.env["mail.mail"].search_count(
            [
                ("model", "=", "res.company"),
                ("res_id", "=", self.company.id),
                ("state", "=", "outgoing"),
                ("subject", "=", "Unauthorized electronic documents"),
                ("body", "ilike", invoice.name),
            ]
        )
        # document is authorized, no mail should be sent
        self.assertEqual(mails_to_send, 0)
