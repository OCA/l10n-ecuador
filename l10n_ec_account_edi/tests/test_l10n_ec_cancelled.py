from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests import tagged

from odoo.addons.l10n_ec_account_edi.models.account_edi_document import (
    AccountEdiDocument,
)

from .sri_response import patch_service_sri
from .test_edi_common import TestL10nECEdiCommon


@tagged("post_install_l10n", "post_install", "-at_install", "cancelled")
class TestL10nCancelled(TestL10nECEdiCommon):
    @patch_service_sri
    def test_l10n_ec_authorized_to_cancelled_ok(self):
        """
        Create invoice, send to the SRI for authorize and successful cancelled
        """

        def mock_l10n_ec_edi_send_xml_with_auth(edi_doc_instance, client_ws):
            return self._get_response_with_auth(edi_doc_instance)

        def mock_l10n_ec_edi_process_response_auth_cancelled(instance, response):
            is_auth = False
            msj_list = []
            return is_auth, msj_list

        partner = self.partner_with_email
        self._setup_edi_company_ec()
        invoice = self._l10n_ec_prepare_edi_out_invoice(
            partner=partner, auto_post=False
        )
        invoice.action_post()
        edi_doc = invoice._get_edi_document(self.edi_format)

        # for authorize
        with patch.object(
            AccountEdiDocument,
            "_l10n_ec_edi_send_xml_auth",
            mock_l10n_ec_edi_send_xml_with_auth,
        ):
            edi_doc._process_documents_web_services(with_commit=False)

        with patch.object(
            AccountEdiDocument,
            "_l10n_ec_edi_send_xml_auth",
            mock_l10n_ec_edi_send_xml_with_auth,
        ), patch.object(
            AccountEdiDocument,
            "_l10n_ec_edi_process_response_auth",
            mock_l10n_ec_edi_process_response_auth_cancelled,
        ):
            invoice.button_cancel_posted_moves()

        self.assertEqual(edi_doc.state, "to_cancel")

        cron_tasks = self.env.ref("account_edi.ir_cron_edi_network", False)
        self.assertTrue(cron_tasks)
        # Execute cron for cancel receipt
        cron_tasks.method_direct_trigger()
        self.assertEqual(invoice.state, "cancel")

    @patch_service_sri
    def test_l10n_ec_authorized_to_cancelled_fail(self):
        """
        Create invoice, send to the SRI for authorize and unsuccessful cancelled
        """

        def mock_l10n_ec_edi_send_xml_with_auth(edi_doc_instance, client_ws):
            return self._get_response_with_auth(edi_doc_instance)

        partner = self.partner_with_email
        self._setup_edi_company_ec()
        invoice = self._l10n_ec_prepare_edi_out_invoice(
            partner=partner, auto_post=False
        )
        invoice.action_post()
        edi_doc = invoice._get_edi_document(self.edi_format)

        # for authorize
        with patch.object(
            AccountEdiDocument,
            "_l10n_ec_edi_send_xml_auth",
            mock_l10n_ec_edi_send_xml_with_auth,
        ):
            edi_doc._process_documents_web_services(with_commit=False)

        # Receipt is authorized
        with patch.object(
            AccountEdiDocument,
            "_l10n_ec_edi_send_xml_auth",
            mock_l10n_ec_edi_send_xml_with_auth,
        ), self.assertRaises(ValidationError):
            invoice.button_cancel_posted_moves()
