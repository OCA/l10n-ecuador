import base64
import datetime
import os
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tools import misc

from odoo.addons.l10n_ec_account_edi.models import sri_key_type

from .test_edi_common import TestL10nECEdiCommon


@tagged("post_install_l10n", "post_install", "-at_install", "certificate")
class TestL10nCheckCertificate(TestL10nECEdiCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
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
        file_path = os.path.join(
            "l10n_ec_account_edi", "tests", "certificates", "invalid.p12"
        )
        file_content = misc.file_open(file_path, mode="rb").read()
        cls.cert6 = cert.create(
            {
                "name": "Invalid PKCS12",
                "file_name": "invalid.p12",
                "password": "123456",
                "file_content": file_content,
                "company_id": cls.company_data["company"].id,
            },
        )

    def _mock_empty_certificate(self, *args, **kwargs):
        return (None, None, [])

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

    def test_l10n_ec_cert_invalid_pkcs12_format(self):
        """Test that invalid PKCS#12 format raises UserError"""
        with self.assertRaisesRegex(
            UserError,
            "Error opening the signature. Wrong password or unsupported file.",
        ):
            with self.assertLogs(
                "odoo.addons.l10n_ec_account_edi.models.sri_key_type", level="WARNING"
            ) as log_catched:
                self.cert6._decode_certificate()
                self.assertIn(
                    "PKCS#12 load failed",
                    log_catched.output[0],
                )

    def test_l10n_ec_cert_no_content_no_password(self):
        """
        Test that missing content and password
        raises UserError
        """
        cert = self.env["sri.key.type"].create(
            {
                "name": "No Content No Password",
                "file_name": "no_password.p12",
                "file_content": base64.b64encode(b"with content"),
            }
        )
        with self.assertRaisesRegex(UserError, "Certificate/password not provided."):
            cert._decode_certificate()

        cert = self.env["sri.key.type"].create(
            {
                "name": "No Content No Content",
                "file_name": "no_content.p12",
                "password": "123456",
            }
        )
        with self.assertRaisesRegex(UserError, "Certificate/password not provided."):
            cert._decode_certificate()

    def test_l10n_ec_cert_pkcs12_no_key_certificate(self):
        """
        Test that PKCS#12 without private key or end-entity
        certificate raises UserError
        """
        # Usar un certificado válido pero mockear la respuesta para que devuelva None
        cert = self.env["sri.key.type"].create(
            {
                "name": "Mock No Key No Certificate",
                "file_name": "mock_no_key.p12",
                "password": "123456",
                "file_content": base64.b64encode(b"dummy_content"),
                "company_id": self.company_data["company"].id,
            }
        )

        with patch.object(
            sri_key_type.pkcs12,
            "load_key_and_certificates",
            self._mock_empty_certificate,
        ):
            with self.assertRaisesRegex(
                UserError,
                "PKCS#12 does not contain a private key and end-entity certificate.",
            ):
                cert._decode_certificate()

    def test_l10n_ec_cert_selection_with_digital_signature(self):
        """
        Test that cert with digital_signature is selected from
        other_certs when main cert doesn't have it
        """
        file_path = os.path.join(
            "l10n_ec_account_edi", "tests", "certificates", "cert_selection.p12"
        )
        file_content_binary = misc.file_open(file_path, mode="rb").read()
        file_content = base64.b64encode(file_content_binary)
        cert = self.env["sri.key.type"].create(
            {
                "name": "Cert Selection Test",
                "file_name": "cert_selection.p12",
                "password": "123456",
                "file_content": file_content,
                "company_id": self.company_data["company"].id,
            }
        )

        # Decodificar y verificar que selecciona el certificado correcto
        private_key, selected_cert, _ = cert._decode_certificate()

        # Debe haber seleccionado el certificado con digital_signature de other_certs
        self.assertIsNotNone(private_key, "Should have private key")
        self.assertIsNotNone(selected_cert, "Should have selected cert")

        # El certificado seleccionado debe tener digital_signature=True
        from cryptography.x509.oid import ExtensionOID, NameOID

        ku = selected_cert.extensions.get_extension_for_oid(
            ExtensionOID.KEY_USAGE
        ).value
        self.assertTrue(
            ku.digital_signature,
            "Selected certificate should have " "digital_signature=True",
        )

        # Verificar que el subject sea el del certificado con digital_signature
        subject_cn = selected_cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[
            0
        ].value
        self.assertEqual(
            subject_cn,
            "Cert With Digital Signature",
            "Should have selected the cert with digital_signature",
        )
