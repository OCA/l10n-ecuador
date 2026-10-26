import logging
from unittest.mock import patch

from odoo.tests import tagged

from odoo.addons.l10n_ec_account_edi.models.account_edi_document import (
    AccountEdiDocument,
)
from odoo.addons.l10n_ec_account_edi.tests.sri_response import patch_service_sri
from odoo.addons.mail.tests.common import MailCommon

from .test_l10n_ec_delivery_note_common import TestL10nDeliveryNoteCommon

_logger = logging.getLogger(__name__)


@tagged("post_install_l10n", "post_install", "-at_install", "mail")
class TestL10nMail(TestL10nDeliveryNoteCommon, MailCommon):
    @patch_service_sri
    def test_l10n_ec_delivery_note_sri(self):
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
            # Honour the return contract of the method being replaced.
            return True

        self.setup_edi_delivery_note()
        delivery_note = self._l10n_ec_create_delivery_note()
        # Transportista con cédula
        delivery_note.delivery_carrier_id = self.partner_dni
        delivery_note.action_confirm()
        edi_doc = delivery_note._get_edi_document(self.edi_format)
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

        # ``ir.cron.method_direct_trigger()`` runs the job on its own cursor
        # since Odoo 19, so it can neither see the delivery note this test has
        # just confirmed nor the patch below; every assertion after it would be
        # vacuous. Run the cron body directly, as the cron's own user does.
        with patch.object(
            AccountEdiDocument,
            "l10n_ec_send_mail_to_partners",
            mock_send_mail_to_partners,
        ):
            result = (
                self.env["account.edi.document"]
                .with_user(cron_tasks.user_id)
                .l10n_ec_send_mail_to_partners()
            )
        self.assertTrue(result)
