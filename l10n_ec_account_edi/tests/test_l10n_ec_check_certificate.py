import base64
import datetime
import logging
import os

from odoo import fields
from odoo.tests import tagged
from odoo.tools import misc

from .test_edi_common import TestL10nECEdiCommon

_logger = logging.getLogger(__name__)


@tagged("post_install_l10n", "post_install", "-at_install", "certificate")
class TestL10nCheckCertificate(TestL10nECEdiCommon):
    """Tests para verificación de certificados y notificaciones de expiración"""

    @classmethod
    def setUpClass(cls):
        """Configurar certificados de prueba con diferentes estados de expiración"""
        super().setUpClass()

        cert = cls.env["sri.key.type"]

        # Cargar el certificado de prueba real
        file_path = os.path.join(
            "l10n_ec_account_edi", "tests", "certificates", "test.p12"
        )
        file_content = misc.file_open(file_path, mode="rb").read()

        # Marcar certificados existentes como expirados
        cert_to_delete = cert.search([("name", "=", "Test")])
        if cert_to_delete:
            cert_to_delete.write({"state": "expired"})

        # Certificados de prueba con distintos escenarios
        cls.cert1 = cert.create(
            {
                "name": "Cert 1",
                "file_name": "cert1.p12",
                "expire_date": fields.Date.context_today(cert),
                "state": "valid",
                "company_id": cls.company.id,
            }
        )

        cls.cert2 = cert.create(
            {
                "name": "Cert 2",
                "file_name": "cert2.p12",
                "expire_date": fields.Date.context_today(cert)
                + datetime.timedelta(days=31),
                "state": "valid",
                "company_id": cls.company.id,
            }
        )

        cls.cert3 = cert.create(
            {
                "name": "Cert 3",
                "file_name": "cert3.p12",
                "state": "valid",
                "company_id": cls.company.id,
            }
        )

        cls.cert4 = cert.create(
            {
                "name": "Cert 4",
                "file_name": "cert4.p12",
                "expire_date": fields.Date.context_today(cert)
                + datetime.timedelta(days=60),
                "days_for_notification": 90,
                "state": "valid",
                "company_id": cls.company.id,
            }
        )

        cls.cert5 = cert.create(
            {
                "name": "Cert 5",
                "file_name": "cert5.p12",
                "expire_date": fields.Date.context_today(cert)
                - datetime.timedelta(days=1),
                "days_for_notification": 30,
                "state": "valid",
                "company_id": cls.company.id,
            }
        )

        # Certificado real de prueba para validación EDI
        cls.test_certificate = cert.create(
            {
                "name": "Test Certificate for EDI",
                "file_name": "test.p12",
                "password": "123456",
                "file_content": base64.b64encode(file_content),
                "company_id": cls.company.id,
            }
        )

    def setUp(self):
        """Configurar el entorno EDI antes de cada test"""
        super().setUp()

        # Validar y cargar el certificado de prueba
        try:
            self.test_certificate.action_validate_and_load()
        except Exception as e:
            self.skipTest(
                f"No se pudo cargar el certificado de prueba: {e}. "
                "Asegúrate de tener un certificado válido en "
                "l10n_ec_account_edi/tests/certificates/test.p12"
            )

        # Configurar la compañía con el certificado
        self.company.write(
            {
                "vat": "1313109678001",
                "currency_id": self.env.ref("base.USD").id,
                "l10n_ec_type_environment": "test",
                "l10n_ec_key_type_id": self.test_certificate.id,
                "l10n_ec_invoice_version": "1.1.0",
            }
        )

        # Configurar partner de la compañía
        required_accounting = self.env["account.fiscal.position"].search(
            [("name", "like", "Persona natural obligada a llevar contabilidad")],
            limit=1,
        )
        if required_accounting:
            self.partner_contact.write(
                {
                    "l10n_latam_identification_type_id": self.env.ref(
                        "l10n_ec.ec_ruc"
                    ).id,
                    "street": "SN",
                    "property_account_position_id": required_accounting.id,
                }
            )

    def test_l10n_ec_check_certificate(self):
        """Verifica notificaciones de certificados"""
        Mail = self.env["mail.mail"]

        # Ejecutar cron de notificación
        self.env["sri.key.type"].action_email_notification()

        certs_no_send = self.cert1 + self.cert2 + self.cert3 + self.cert5
        mails_to_send = Mail.search_count(
            [
                ("model", "=", certs_no_send._name),
                ("res_id", "in", certs_no_send.ids),
                ("state", "=", "outgoing"),
            ]
        )
        self.assertEqual(
            mails_to_send,
            0,
            f"No se esperaban emails para los certificados "
            f"{certs_no_send.mapped('name')}",
        )

        mails_to_send = Mail.search_count(
            [
                ("model", "=", self.cert4._name),
                ("res_id", "=", self.cert4.id),
                ("state", "=", "outgoing"),
            ]
        )
        self.assertEqual(
            mails_to_send,
            1,
            f"Se esperaba 1 email para el certificado {self.cert4.name}",
        )

    def test_certificate_expiration_calculation(self):
        """Verifica cálculo de días hasta expiración"""
        today = fields.Date.context_today(self.env["sri.key.type"])
        days_to_expire = (self.cert4.expire_date - today).days
        self.assertEqual(days_to_expire, 60, "El certificado 4 debe expirar en 60 días")
        self.assertLess(
            days_to_expire,
            self.cert4.days_for_notification,
            "Los días hasta expirar deben ser menores que días de notificación",
        )

    def test_certificate_validation(self):
        """Verifica que el certificado de prueba es válido"""
        self.assertTrue(
            self.test_certificate.exists(),
            "El certificado de prueba debe existir",
        )
        self.assertEqual(
            self.test_certificate.state,
            "valid",
            "El certificado debe estar en estado válido",
        )

        try:
            _private_key, cert = self.test_certificate._decode_certificate()
            self.assertTrue(cert, "El certificado debe decodificarse correctamente")
        except Exception as e:
            self.fail(f"El certificado no se pudo decodificar: {e}")
