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

        with (
            patch.object(
                AccountEdiDocument,
                "_l10n_ec_edi_send_xml_auth",
                mock_l10n_ec_edi_send_xml_with_auth,
            ),
            patch.object(
                AccountEdiDocument,
                "_l10n_ec_edi_process_response_auth",
                mock_l10n_ec_edi_process_response_auth_cancelled,
            ),
        ):
            invoice.button_cancel_posted_moves()

        self.assertEqual(edi_doc.state, "to_cancel")

        cron_tasks = self.env.ref("account_edi.ir_cron_edi_network", False)
        self.assertTrue(cron_tasks)
        # Run the cancel job in this transaction. ``ir.cron.method_direct_trigger()``
        # used to run the job on the caller's cursor (17.0), but since 19.0 it
        # opens its own connection and commits there (ir_cron.py::_run_job and
        # ``_callback``). The job therefore neither sees the ``to_cancel`` document
        # this test has just written nor can it ``SELECT ... FOR UPDATE NOWAIT``
        # that row, so ``_process_documents_web_services()`` swallows the LockError
        # and processes nothing. Calling the same in-transaction entry point the
        # rest of this suite uses keeps the assertion on real behaviour.
        edi_doc._process_documents_web_services(with_commit=False)
        self.assertEqual(edi_doc.state, "cancelled")
        self.assertEqual(invoice.state, "cancel")
        self.assertFalse(invoice.show_reset_to_draft_button)

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
        with (
            patch.object(
                AccountEdiDocument,
                "_l10n_ec_edi_send_xml_auth",
                mock_l10n_ec_edi_send_xml_with_auth,
            ),
            self.assertRaises(ValidationError),
        ):
            invoice.button_cancel_posted_moves()
