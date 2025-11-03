import logging
from base64 import b64encode
from pathlib import Path

from odoo.exceptions import UserError  # <-- agrega esto
from odoo.tests.common import TransactionCase, tagged

_logger = logging.getLogger(__name__)


@tagged("test_simple")
class TestDecodeCertificate(TransactionCase):
    def setUp(self):
        super().setUp()
        self.cert_file = Path(__file__).parent / "certificates" / "test.p12"
        self.password = "123456"  # Contraseña real del archivo .p12

    def test_cert_file_exists(self):
        """Verifica que el archivo de certificado exista"""
        self.assertTrue(
            self.cert_file.exists(), f"El archivo {self.cert_file} no existe"
        )
        _logger.warning("✅ Archivo de certificado encontrado: %s", self.cert_file)

    def test_decode_certificate_success(self):
        """Prueba que _decode_certificate carga correctamente el certificado"""
        file_content = b64encode(self.cert_file.read_bytes()).decode()

        cert_obj = self.env["sri.key.type"].new(
            {
                "file_content": file_content,
                "password": self.password,
            }
        )

        try:
            private_key, certificate = cert_obj._decode_certificate()
        except Exception as e:
            self.fail(f"_decode_certificate falló: {e}")

        self.assertIsNotNone(private_key, "No se cargó la clave privada")
        self.assertIsNotNone(certificate, "No se cargó el certificado")
        _logger.info("✅ _decode_certificate pasó correctamente")

    def test_decode_certificate_wrong_password(self):
        """Prueba que _decode_certificate falla con contraseña incorrecta"""
        file_content = b64encode(self.cert_file.read_bytes()).decode()

        cert_obj = self.env["sri.key.type"].new(
            {
                "file_content": file_content,
                "password": "wrong_password",
            }
        )

        with self.assertRaises(UserError):
            cert_obj._decode_certificate()
        _logger.info(
            "✅ _decode_certificate falla correctamente con contraseña incorrecta"
        )
