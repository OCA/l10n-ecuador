import datetime

from odoo import fields
from odoo.tests import tagged

from .test_edi_common import TestL10nECEdiCommon


@tagged("post_install_l10n", "post_install", "-at_install", "certificate")
class TestL10nCheckCertificate(TestL10nECEdiCommon):
    @classmethod
    def setUpClass(
        cls,
        chart_template_ref="ec",
        edi_format_ref="l10n_ec_account_edi.edi_format_ec_sri",
    ):
        super().setUpClass(
            chart_template_ref=chart_template_ref, edi_format_ref=edi_format_ref
        )
        cert = cls.env["sri.key.type"]
        cert_to_delete = cert.search([("name", "=", "Test")])
        cert_to_delete.write({"state": "expired"})
        # Not send, because it is expired today
        cls.cert1 = cert.create(
            {
                "name": "Cert 1",
                "file_name": "cert1.p12",
                "expire_date": fields.Date.context_today(cert),
                "state": "valid",
            }
        )
        # Not send, because it is expired in 31 days and days for notification is 30
        cls.cert2 = cert.create(
            {
                "name": "Cert 2",
                "file_name": "cert2.p12",
                "expire_date": fields.Date.context_today(cert)
                + datetime.timedelta(days=31),
                "state": "valid",
            }
        )
        # Not send, because it is expired. Expire date default is today
        cls.cert3 = cert.create(
            {"name": "Cert 3", "file_name": "cert3.p12", "state": "valid"}
        )
        # Send, because days to expire is less than days for notification
        cls.cert4 = cert.create(
            {
                "name": "Cert 4",
                "file_name": "cert4.p12",
                "expire_date": fields.Date.context_today(cert)
                + datetime.timedelta(days=60),
                "days_for_notification": 90,
                "state": "valid",
            }
        )
        # Not send, because it is expired, but expired with negative days
        cls.cert5 = cert.create(
            {
                "name": "Cert 5",
                "file_name": "cert5.p12",
                "expire_date": fields.Date.context_today(cert)
                - datetime.timedelta(days=1),
                "days_for_notification": 30,
                "state": "valid",
            }
        )

    def test_l10n_ec_check_certificate(self):
        """Test that the cron task is executed correctly."""
        Mail = self.env["mail.mail"]
        self._setup_edi_company_ec()
        self.env["sri.key.type"].action_email_notification()
        certs_no_send = self.cert1 + self.cert2 + self.cert3 + self.cert5
        mails_to_send = Mail.search_count(
            [
                ("model", "=", certs_no_send._name),
                ("res_id", "in", certs_no_send.ids),
                ("state", "=", "outgoing"),
            ]
        )
        self.assertEqual(mails_to_send, 0)
        mails_to_send = Mail.search_count(
            [
                ("model", "=", self.cert4._name),
                ("res_id", "=", self.cert4.id),
                ("state", "=", "outgoing"),
            ]
        )
        self.assertEqual(mails_to_send, 1)
