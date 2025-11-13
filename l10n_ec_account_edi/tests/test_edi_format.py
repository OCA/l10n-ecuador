from odoo.tests import tagged

from .test_edi_common import TestL10nECEdiCommon


@tagged("post_install", "-at_install")
class TestAccountEdiFormat(TestL10nECEdiCommon):
    def test_is_required_for_invoice(self):
        """Verificar si se requiere edi_format en las facturas
        y si es compatible con el diario"""
        invoice = self._l10n_ec_create_in_invoice()
        self.assertFalse(self.edi_format._get_move_applicability(invoice))
        # Cambiar los datos de la factura
        invoice.company_id.country_id = self.env.ref("base.co")
        invoice.journal_id.type = "sale"
        invoice.move_type = "out_invoice"
        self.assertTrue(self.edi_format._get_move_applicability(invoice))
        # Comprobar si el edi_format es compatible con el diario
        self.assertTrue(self.edi_format._is_compatible_with_journal(invoice.journal_id))

    def test_l10n_ec_tax_without_code_ats_for_withhold(self):
        """Test error when withholding tax doesn't have l10n_ec_code_ats"""
        self._setup_edi_company_ec()
        invoice = self._l10n_ec_prepare_edi_out_invoice()

        # Crear impuesto de retención sin code_ats
        tax_group = self.env["account.tax.group"].search(
            [("l10n_ec_type", "=", "withhold_income_sale")], limit=1
        )
        if not tax_group:
            tax_group = self.env["account.tax.group"].create(
                {
                    "name": "Retención Renta Venta",
                    "l10n_ec_type": "withhold_income_sale",
                }
            )

        withhold_tax = self.env["account.tax"].create(
            {
                "name": "Test Withhold Tax",
                "amount": 1.0,
                "tax_group_id": tax_group.id,
                "l10n_ec_code_ats": False,  # No configurado
            }
        )

        invoice.invoice_line_ids[0].tax_ids = [(4, withhold_tax.id)]
        errors = self.edi_format._check_move_configuration(invoice)
        self.assertTrue(
            any("You must set Code Base into Tax" in error for error in errors)
        )

    def test_l10n_ec_tax_without_xml_fe_code(self):
        """Test error when regular tax doesn't have l10n_ec_xml_fe_code"""
        self._setup_edi_company_ec()
        invoice = self._l10n_ec_prepare_edi_out_invoice()

        # Crear impuesto sin xml_fe_code
        tax = self.env["account.tax"].create(
            {
                "name": "Test Tax without FE Code",
                "amount": 12.0,
                "l10n_ec_xml_fe_code": False,  # No configurado
            }
        )

        invoice.invoice_line_ids[0].tax_ids = [(6, 0, [tax.id])]
        errors = self.edi_format._check_move_configuration(invoice)
        self.assertTrue(
            any(
                "You must set Tax Code for Electronic Documents" in error
                for error in errors
            )
        )

    def test_l10n_ec_invoice_without_payment_method(self):
        """Test error when invoice has no payment method"""
        self._setup_edi_company_ec()
        invoice = self._l10n_ec_prepare_edi_out_invoice()

        # Eliminar método de pago
        invoice.l10n_ec_sri_payment_id = False
        invoice.journal_id.l10n_ec_sri_payment_id = False

        errors = self.edi_format._check_move_configuration(invoice)
        self.assertTrue(
            any("You must set Payment Method SRI" in error for error in errors)
        )

    def test_l10n_ec_debit_note_without_version(self):
        """Test error when debit note doesn't have version configured"""
        self._setup_edi_company_ec()
        invoice = self._l10n_ec_prepare_edi_debit_note()

        # Eliminar versión de nota de débito
        invoice.company_id.l10n_ec_debit_note_version = False

        errors = self.edi_format._check_move_configuration(invoice)
        self.assertTrue(
            any(
                "You must set XML Version for Debit Note into company" in error
                for error in errors
            )
        )

    def test_l10n_ec_credit_note_without_version(self):
        """Test error when credit note doesn't have version configured"""
        self._setup_edi_company_ec()
        invoice = self._l10n_ec_prepare_edi_credit_note()

        # Eliminar versión de nota de crédito
        invoice.company_id.l10n_ec_credit_note_version = False

        errors = self.edi_format._check_move_configuration(invoice)
        self.assertTrue(
            any(
                "You must set XML Version for Credit Note into company" in error
                for error in errors
            )
        )

    def test_l10n_ec_invoice_without_partner_vat(self):
        """Test error when partner doesn't have VAT"""
        self._setup_edi_company_ec()
        invoice = self._l10n_ec_prepare_edi_out_invoice()

        # Eliminar VAT del partner
        invoice.commercial_partner_id.vat = False

        errors = self.edi_format._check_move_configuration(invoice)
        self.assertTrue(
            any(
                "You must set vat identification for Partner" in error
                for error in errors
            )
        )

    def test_l10n_ec_invoice_without_company_vat(self):
        """Test error when company doesn't have VAT"""
        self._setup_edi_company_ec()
        invoice = self._l10n_ec_prepare_edi_out_invoice()

        # Eliminar VAT de la compañía
        invoice.company_id.vat = False

        errors = self.edi_format._check_move_configuration(invoice)
        self.assertTrue(
            any(
                "You must set vat identification for company" in error
                for error in errors
            )
        )

    def test_l10n_ec_invoice_without_certificate(self):
        """Test error when company doesn't have certificate"""
        self._setup_edi_company_ec()
        invoice = self._l10n_ec_prepare_edi_out_invoice()

        # Eliminar certificado
        invoice.company_id.l10n_ec_key_type_id = False

        errors = self.edi_format._check_move_configuration(invoice)
        self.assertTrue(
            any(
                "You must set Electronic Certificate File into company" in error
                for error in errors
            )
        )

    def test_l10n_ec_invoice_without_emission_address(self):
        """Test error when journal doesn't have emission address"""
        self._setup_edi_company_ec()
        invoice = self._l10n_ec_prepare_edi_out_invoice()

        # Eliminar dirección de emisión
        invoice.journal_id.l10n_ec_emission_address_id = False

        errors = self.edi_format._check_move_configuration(invoice)
        self.assertTrue(
            any(
                "You must set Emission address into Journal" in error
                for error in errors
            )
        )

    def test_l10n_ec_invoice_emission_address_without_street(self):
        """Test error when emission address doesn't have street"""
        self._setup_edi_company_ec()
        invoice = self._l10n_ec_prepare_edi_out_invoice()

        # Eliminar calle de la dirección de emisión
        invoice.journal_id.l10n_ec_emission_address_id.street = False

        errors = self.edi_format._check_move_configuration(invoice)
        self.assertTrue(
            any(
                "You must set street into Emission Address" in error for error in errors
            )
        )

    def test_l10n_ec_liquidation_without_version(self):
        """Test error when purchase liquidation doesn't have version configured"""
        self._setup_edi_company_ec()
        invoice = self._l10n_ec_prepare_edi_liquidation()

        # Eliminar versión de liquidación de compra
        invoice.company_id.l10n_ec_liquidation_version = False

        errors = self.edi_format._check_move_configuration(invoice)
        self.assertTrue(
            any(
                "You must set XML Version for Purchase Liquidation into company"
                in error
                for error in errors
            )
        )

    def test_l10n_ec_get_edi_ws_client_connection_error(self):
        """Test error when connection to SRI web service fails"""
        from unittest.mock import patch

        self._setup_edi_company_ec()

        # Mock zeep.Client to raise an exception
        with patch(
            "odoo.addons.l10n_ec_account_edi.models.account_edi_format.Client"
        ) as mock_client:
            mock_client.side_effect = Exception("Connection timeout")

            # Capturar los warnings generados
            with self.assertLogs(
                "odoo.addons.l10n_ec_account_edi.models.account_edi_format",
                level="WARNING",
            ) as log_catcher:
                # Intentar obtener cliente de recepción
                client = self.edi_format._l10n_ec_get_edi_ws_client("test", "reception")

                # Verificar que retorna None cuando hay error
                self.assertIsNone(client)

                # Intentar obtener cliente de autorización
                client = self.edi_format._l10n_ec_get_edi_ws_client(
                    "production", "authorization"
                )

                # Verificar que retorna None cuando hay error
                self.assertIsNone(client)

            # Verificar que se registraron los warnings esperados
            self.assertEqual(len(log_catcher.output), 2)
            self.assertIn(
                "Error in Connection with web services of SRI", log_catcher.output[0]
            )
            self.assertIn("Connection timeout", log_catcher.output[0])
            self.assertIn(
                "Error in Connection with web services of SRI", log_catcher.output[1]
            )
            self.assertIn("Connection timeout", log_catcher.output[1])
