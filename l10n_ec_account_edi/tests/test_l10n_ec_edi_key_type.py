from odoo.exceptions import UserError
from odoo.tests import tagged

from .test_edi_common import TestL10nECEdiCommon


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
