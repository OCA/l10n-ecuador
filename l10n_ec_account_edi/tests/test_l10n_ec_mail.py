from unittest.mock import patch

from odoo.tests import tagged

from odoo.addons.l10n_ec_account_edi.models.account_edi_document import (
    AccountEdiDocument,
)
from odoo.addons.mail.tests.common import MailCommon

from .sri_response import patch_service_sri
from .test_edi_common import TestL10nECEdiCommon


@tagged("post_install_l10n", "post_install", "-at_install", "mail")
class TestL10nMail(TestL10nECEdiCommon, MailCommon):
    @patch_service_sri
    def test_l10n_ec_cron_invoice(self):
        def mock_l10n_ec_edi_send_xml_with_auth(edi_doc_instance, client_ws):
            return self._get_response_with_auth(edi_doc_instance)

        def mock_send_mail_to_partners(instance):
            # search company with environment test instead of production
            all_companies = instance.env["res.company"].search(
                [
                    ("partner_id.country_id.code", "=", "EC"),
                    ("l10n_ec_type_environment", "=", "test"),
                ]
            )
            for company in all_companies:
                instance.with_company(company).l10n_ec_send_mail_to_partner()

        partner = self.partner_with_email
        self._setup_edi_company_ec()
        invoice = self._l10n_ec_prepare_edi_out_invoice(
            partner=partner, auto_post=False
        )
        invoice.action_post()
        edi_doc = invoice._get_edi_document(self.edi_format)

        with patch.object(
            AccountEdiDocument,
            "_l10n_ec_edi_send_xml_auth",
            mock_l10n_ec_edi_send_xml_with_auth,
        ):
            edi_doc._process_documents_web_services(with_commit=False)

        cron_tasks = self.env.ref(
            "l10n_ec_account_edi.ir_cron_send_email_electronic_documents", False
        )
        self.assertTrue(cron_tasks)

        with patch.object(
            AccountEdiDocument,
            "l10n_ec_send_mail_to_partners",
            mock_send_mail_to_partners,
        ):
            result = cron_tasks.method_direct_trigger()
        self.assertTrue(result)
        self.assertEqual(invoice.state, "posted")
        self.assertTrue(edi_doc.l10n_ec_xml_access_key)
        self.assertTrue(invoice.is_move_sent)
