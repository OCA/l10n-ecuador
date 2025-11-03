import logging
from pathlib import Path

from odoo.tests.common import TransactionCase

_logger = logging.getLogger(__name__)


class TestSimple(TransactionCase):
    def setUp(self):
        super().setUp()
        # Ruta al certificado
        self.cert_file = Path(__file__).parent / "certificates" / "test.p12"

    def test_cert_file_exists(self):
        """Verifica que el certificado exista en la carpeta correcta"""
        self.assertTrue(
            self.cert_file.exists(), f"El archivo {self.cert_file} no existe"
        )
        _logger.info("✅ El archivo de certificado existe: %s", self.cert_file)

    def test_dummy(self):
        """Test dummy para asegurarnos que los tests corren"""
        self.assertEqual(1 + 1, 2, "La suma básica falla")
        _logger.info("✅ Test dummy pasado correctamente")
