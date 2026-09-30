import base64

from odoo.exceptions import UserError
from odoo.tests import tagged

from .test_edi_common import TestL10nECEdiCommon, _generate_test_p12


@tagged("post_install_l10n", "post_install", "-at_install")
class TestL10nECKeyType(TestL10nECEdiCommon):
    def test_l10n_ec_load_key_type(self):
        # Validar la firma correcta, e informar la fecha de expiración
        self.certificate.action_validate_and_load()
        self.assertEqual(self.certificate.state, "valid")

    def test_invalid_key_type(self):
        # Validar la firma con contraseña equivocada
        self.certificate.password = "invalid"
        with self.assertRaises(UserError):
            self.certificate.action_validate_and_load()

    def test_expired_key_type_blocks_signing(self):
        # Una firma vencida debe cargar pero negarse a firmar con un
        # mensaje accionable, en lugar de fallar en silencio río abajo.
        expired_certificate = (
            self.env["sri.key.type"]
            .sudo()
            .create(
                {
                    "name": "Test expired",
                    "file_name": "test-expired.p12",
                    "password": "123456",
                    "file_content": base64.b64encode(_generate_test_p12(expired=True)),
                    "company_id": self.company_data["company"].id,
                },
            )
        )
        self.assertTrue(expired_certificate.action_validate_and_load())
        with self.assertRaisesRegex(UserError, "expired"):
            expired_certificate.action_sign(b"<test/>")
