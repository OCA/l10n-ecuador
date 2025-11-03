import logging
from datetime import datetime
from pathlib import Path

from odoo.tests import tagged

from .test_edi_common import TestL10nECEdiCommon

_logger = logging.getLogger(__name__)


@tagged("post_install_l10n", "post_install", "-at_install")
class TestEdiDocument(TestL10nECEdiCommon):
    """Tests para funcionalidad de account.edi.document"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Ruta al certificado
        cls.cert_file = Path(__file__).parent / "certificates" / "test.p12"

    def setUp(self):
        super().setUp()
        # Solo configurar la compañía básica de Ecuador
        self._setup_company_ec()

    def test_cert_file_exists(self):
        """Verifica que el certificado exista en la carpeta correcta"""
        self.assertTrue(
            self.cert_file.exists(),
            f"El archivo {self.cert_file} no existe",
        )

    def test_dummy(self):
        """Test dummy para asegurarnos que los tests corren"""
        self.assertEqual(1 + 1, 2, "La suma básica falla")

    def test_generate_access_key_and_check_digit(self):
        """Prueba la generación de access key y dígito verificador"""
        today = datetime.today()

        invoice = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": self.partner_cf.id,
                "invoice_date": today,
            }
        )

        edi_doc = self.env["account.edi.document"].create(
            {
                "move_id": invoice.id,
                "edi_format_id": self.edi_format.id,
                "state": "to_send",
            }
        )

        access_key = edi_doc.l10n_ec_generate_access_key(
            document_code_sri="01",
            complete_document_number="0010010123456789",
            environment="1",
            date_document=today,
            company=self.company,
        )

        self.assertIn(
            len(access_key),
            [49, 50],
            f"La clave de acceso debe tener 49 o 50 dígitos, "
            f"tiene {len(access_key)}: {access_key}",
        )

        access_key_base = access_key[:-1]

        check_digit = edi_doc.l10n_ec_get_check_digit(access_key_base)
        self.assertEqual(
            str(check_digit),
            access_key[-1],
            f"El dígito verificador no coincide. Calculado: {check_digit}, "
            f"En clave: {access_key[-1]}",
        )

    def test_split_document_number(self):
        """Prueba el split de número de documento"""
        invoice = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": self.partner_cf.id,
            }
        )

        edi_doc = self.env["account.edi.document"].create(
            {
                "move_id": invoice.id,
                "edi_format_id": self.edi_format.id,
                "state": "to_send",
            }
        )

        result = edi_doc._l10n_ec_split_document_number("001-002-000123456")
        self.assertEqual(result, ("001", "002", "000123456"))

    def test_prepare_tax_vals_edi(self):
        """Prueba la preparación de valores de impuestos para EDI"""
        invoice = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": self.partner_cf.id,
            }
        )

        edi_doc = self.env["account.edi.document"].create(
            {
                "move_id": invoice.id,
                "edi_format_id": self.edi_format.id,
                "state": "to_send",
            }
        )

        tax_group = self.env["account.tax.group"].create(
            {"name": "IVA", "l10n_ec_xml_fe_code": "2"}
        )

        tax_obj = self.env["account.tax"].create(
            {
                "name": "IVA 12%",
                "amount": 12.0,
                "type_tax_use": "sale",
                "l10n_ec_xml_fe_code": "2",
                "tax_group_id": tax_group.id,
            }
        )

        tax_data = {
            "tax": tax_obj,
            "base_amount_currency": 100,
            "tax_amount_currency": 12,
        }

        vals = edi_doc._l10n_ec_prepare_tax_vals_edi(tax_data)
        self.assertEqual(vals["codigoPorcentaje"], "2")
        self.assertEqual(float(vals["baseImponible"]), 100.0)
        self.assertEqual(float(vals["valor"]), 12.0)

    def test_clean_str_and_number_format(self):
        """Prueba limpieza de strings y formato de números"""
        invoice = self.env["account.move"].create(
            {"move_type": "out_invoice", "partner_id": self.partner_cf.id}
        )

        edi_doc = self.env["account.edi.document"].create(
            {
                "move_id": invoice.id,
                "edi_format_id": self.edi_format.id,
                "state": "to_send",
            }
        )

        clean = edi_doc._l10n_ec_clean_str("áéíóú ñ!@#")
        self.assertEqual(clean, "aeiou n")

        formatted = edi_doc._l10n_ec_number_format(123.456789, 2)
        self.assertEqual(formatted, "123.46")
