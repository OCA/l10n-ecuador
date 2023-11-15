import datetime
from datetime import date

from odoo.tests import tagged

from .test_edi_common import TestL10nECEdiCommon


@tagged("post_install_l10n", "post_install", "-at_install", "certificate")
class TestL10nCheckCertificate(TestL10nECEdiCommon):
    def test_l10n_ec_check_certificate(self):
        """Test that the cron task is executed correctly."""
        self._setup_edi_company_ec()
        self._prepare_certificates()

        cron_tasks = self.env.ref(
            "l10n_ec_account_edi.ir_cron_check_certificate", False
        )
        self.assertTrue(cron_tasks)

        result = cron_tasks.method_direct_trigger()
        self.assertTrue(result)

        mails_send = self.env["mail.message"].search_count(
            [
                "|",
                "|",
                ("subject", "like", "%Cert 4%"),
                ("subject", "like", "%Cert 3%"),
                ("subject", "like", "%Cert 1%"),
                ("model", "=", "sri.key.type"),
                ("message_type", "=", "notification"),
            ]
        )

        self.assertEqual(mails_send, 3)

        no_mails_send = self.env["mail.message"].search_count(
            [
                ("subject", "like", "%Cert 2%"),
                ("model", "=", "sri.key.type"),
                ("message_type", "=", "notification"),
            ]
        )

        self.assertEqual(no_mails_send, 0)

    def _prepare_certificates(self):

        cert = self.env["sri.key.type"]

        cert.create(
            {
                "name": "Cert 1",
                "file_name": "cert1.p12",
                "expire_date": date.today(),
                "state": "valid",
            }
        )
        cert.create(
            {
                "name": "Cert 2",
                "file_name": "cert2.p12",
                "expire_date": date.today() + datetime.timedelta(days=31),
                "state": "valid",
            }
        )
        cert.create({"name": "Cert 3", "file_name": "cert3.p12", "state": "valid"})
        cert.create(
            {
                "name": "Cert 4",
                "file_name": "cert4.p12",
                "expire_date": date.today() + datetime.timedelta(days=60),
                "days_for_notification": 90,
                "state": "valid",
            }
        )
