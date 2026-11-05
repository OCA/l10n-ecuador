"""Import supplier factura XML, by file or by access key.

Both doors feed the same parser and land one draft bill: supplier by
RUC, lines with the purchase tax of each exact VAT rate, SRI number as
vendor reference and authorization. Refusals (malformed XML, missing
RUC/clave/lines, mixed or unknown rates, duplicates, bad keys) arrive
as ``UserError``/``ValidationError`` in Python, before any SQL.

The SRI is never touched: key-path tests mock the request at the
wizard boundary and feed plain-dict responses through the real
envelope unwrapping.
"""

import base64
from unittest import mock

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from odoo.addons.l10n_ec_account_edi.tests.test_common import TestL10nECCommon
from odoo.addons.l10n_ec_xml_import.models.sri_xml import parse_supplier_xml
from odoo.addons.l10n_ec_xml_import.wizard.l10n_ec_xml_import import L10nEcXmlImport

CLAVE = ("1234567890" * 5)[:49]
AUTH_NUMBER = ("9876543210" * 5)[:49]
NEW_RUC = "1790011226001"


def _line(
    code="P001",
    description="Widget",
    qty=2.0,
    price=100.0,
    discount=0.0,
    tax_code="2",
    rate_code="4",
    rate=15.0,
    base=None,
    value=None,
):
    base = qty * price if base is None else base
    value = round(base * rate / 100.0, 2) if value is None else value
    return {
        "code": code,
        "description": description,
        "qty": qty,
        "price": price,
        "discount": discount,
        "tax_code": tax_code,
        "rate_code": rate_code,
        "rate": rate,
        "base": base,
        "value": value,
    }


def _factura_xml(
    number="001-001-000000001",
    ruc=NEW_RUC,
    name="ACME SUPPLIER SA",
    clave=CLAVE,
    date="15/08/2026",
    currency="DOLAR",
    lines=None,
    with_reembolsos=False,
):
    lines = lines if lines is not None else [_line()]
    details = "".join(
        (
            "<detalle>"
            f"<codigoPrincipal>{item['code']}</codigoPrincipal>"
            f"<descripcion>{item['description']}</descripcion>"
            f"<cantidad>{item['qty']}</cantidad>"
            f"<precioUnitario>{item['price']}</precioUnitario>"
            f"<descuento>{item['discount']}</descuento>"
            f"<precioTotalSinImpuesto>"
            f"{item['qty'] * item['price'] - item['discount']}"
            "</precioTotalSinImpuesto>"
            "<impuestos><impuesto>"
            f"<codigo>{item['tax_code']}</codigo>"
            f"<codigoPorcentaje>{item['rate_code']}</codigoPorcentaje>"
            f"<tarifa>{item['rate']}</tarifa>"
            f"<baseImponible>{item['base']}</baseImponible>"
            f"<valor>{item['value']}</valor>"
            "</impuesto></impuestos>"
            "</detalle>"
        )
        for item in lines
    )
    reembolsos = (
        "<reembolsos><reembolsoDetalle>"
        "<codDocReembolso>41</codDocReembolso>"
        "</reembolsoDetalle></reembolsos>"
        if with_reembolsos
        else ""
    )
    estab, pto, secuencial = number.split("-")
    return f"""<factura>
  <infoTributaria>
    <ambiente>2</ambiente>
    <razonSocial>{name}</razonSocial>
    <ruc>{ruc}</ruc>
    <claveAcceso>{clave}</claveAcceso>
    <codDoc>01</codDoc>
    <estab>{estab}</estab>
    <ptoEmi>{pto}</ptoEmi>
    <secuencial>{secuencial}</secuencial>
    <dirMatriz>Av. Test 123</dirMatriz>
  </infoTributaria>
  <infoFactura>
    <fechaEmision>{date}</fechaEmision>
    <moneda>{currency}</moneda>
    <totalSinImpuestos>200.00</totalSinImpuestos>
    <totalDescuento>0.00</totalDescuento>
    <totalConImpuestos><totalImpuesto>
      <codigo>2</codigo>
      <codigoPorcentaje>4</codigoPorcentaje>
      <baseImponible>200.00</baseImponible>
      <valor>30.00</valor>
    </totalImpuesto></totalConImpuestos>
    <importeTotal>230.00</importeTotal>
  </infoFactura>
  <detalles>{details}</detalles>
  {reembolsos}
</factura>"""


def _envelope_xml(inner, numero_autorizacion=AUTH_NUMBER, estado="AUTORIZADO"):
    return f"""<autorizacion>
  <estado>{estado}</estado>
  <numeroAutorizacion>{numero_autorizacion}</numeroAutorizacion>
  <fechaAutorizacion>16/08/2026 10:00:00</fechaAutorizacion>
  <ambiente>2</ambiente>
  <comprobante><![CDATA[{inner}]]></comprobante>
</autorizacion>"""


@tagged("post_install", "-at_install")
class TestL10nEcXmlImport(TestL10nECCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company.write({"currency_id": cls.env.ref("base.USD").id})

    def _import_file(self, xml_text, **values):
        wizard = self.env["l10n.ec.xml.import"].create(
            {
                "xml_file": base64.b64encode(xml_text.encode("utf-8")),
                "xml_filename": "supplier.xml",
                **values,
            }
        )
        action = wizard.action_import()
        return self.env["account.move"].browse(action["res_id"]), action

    def _bill_count(self):
        return self.env["account.move"].search_count(
            [
                ("move_type", "=", "in_invoice"),
                ("company_id", "=", self.company.id),
            ]
        )

    # -- file door ----------------------------------------------------

    def test_import_file_creates_draft_bill(self):
        bill, action = self._import_file(_factura_xml())
        self.assertEqual(bill.state, "draft")
        self.assertEqual(bill.move_type, "in_invoice")
        self.assertEqual(bill.partner_id.vat, NEW_RUC)
        self.assertEqual(bill.partner_id.name, "ACME SUPPLIER SA")
        self.assertEqual(bill.partner_id.supplier_rank, 1)
        self.assertIn(
            self.env.ref("l10n_ec_xml_import.category_imported_supplier").id,
            bill.partner_id.category_id.ids,
        )
        self.assertEqual(bill.l10n_latam_document_number, "001-001-000000001")
        self.assertEqual(bill.ref, "001-001-000000001")
        self.assertEqual(bill.l10n_ec_electronic_authorization, CLAVE)
        self.assertEqual(str(bill.invoice_date), "2026-08-15")
        self.assertEqual(len(bill.invoice_line_ids), 1)
        line = bill.invoice_line_ids
        self.assertEqual(line.name, "Widget")
        self.assertEqual(line.quantity, 2.0)
        self.assertEqual(line.price_unit, 100.0)
        self.assertEqual(line.tax_ids.mapped("amount"), [15.0])
        self.assertTrue(all(tax.type_tax_use == "purchase" for tax in line.tax_ids))
        attachment = self.env["ir.attachment"].search(
            [("res_model", "=", "account.move"), ("res_id", "=", bill.id)]
        )
        self.assertEqual(len(attachment), 1)
        self.assertEqual(action["res_model"], "account.move")
        self.assertEqual(action["res_id"], bill.id)

    def test_import_reuses_existing_supplier(self):
        before = self.env["res.partner"].search_count([("vat", "=", "1313109678001")])
        bill, _action = self._import_file(
            _factura_xml(ruc="1313109678001", name="Test Partner RUC")
        )
        self.assertEqual(bill.partner_id, self.partner_ruc)
        after = self.env["res.partner"].search_count([("vat", "=", "1313109678001")])
        self.assertEqual(before, after)

    def test_import_mixed_rates_across_lines(self):
        bill, _action = self._import_file(
            _factura_xml(
                lines=[
                    _line(),
                    _line(
                        code="P002",
                        description="Exempt",
                        qty=1.0,
                        price=50.0,
                        rate_code="0",
                        rate=0.0,
                    ),
                ]
            )
        )
        self.assertEqual(len(bill.invoice_line_ids), 2)
        amounts = sorted(bill.invoice_line_ids.mapped("tax_ids.amount"))
        self.assertEqual(amounts, [0.0, 15.0])

    def test_import_envelope_file_uses_auth_number(self):
        bill, _action = self._import_file(_envelope_xml(_factura_xml()))
        self.assertEqual(bill.l10n_ec_electronic_authorization, AUTH_NUMBER)
        self.assertEqual(bill.partner_id.vat, NEW_RUC)

    def test_import_file_wins_over_key(self):
        with mock.patch.object(
            L10nEcXmlImport,
            "_l10n_ec_request_authorization",
            side_effect=AssertionError("the key must not be fetched"),
        ):
            bill, _action = self._import_file(_factura_xml(), access_key="0" * 49)
        self.assertEqual(bill.l10n_latam_document_number, "001-001-000000001")

    # -- refusals --------------------------------------------------------

    def test_import_refuses_duplicate(self):
        bill, _action = self._import_file(_factura_xml())
        before = self._bill_count()
        with self.assertRaisesRegex(UserError, "already imported"):
            self._import_file(_factura_xml())
        self.assertEqual(self._bill_count(), before)
        self.assertTrue(bill.exists())

    def test_import_refuses_duplicate_auth_key(self):
        self._import_file(_factura_xml(number="001-001-000000001"))
        with self.assertRaisesRegex(UserError, "already imported"):
            self._import_file(_factura_xml(number="001-001-000000002"))
        self.assertEqual(self._bill_count(), 1)

    def test_import_refuses_malformed_xml(self):
        with self.assertRaisesRegex(UserError, "cannot be parsed"):
            self._import_file("<factura><broken")

    def test_import_refuses_non_factura(self):
        credit_note = _factura_xml().replace("factura>", "notaCredito>", 10)
        with self.assertRaisesRegex(UserError, "Only supplier facturas"):
            self._import_file(credit_note)

    def test_import_refuses_missing_ruc(self):
        xml = _factura_xml().replace(f"<ruc>{NEW_RUC}</ruc>", "<ruc></ruc>")
        with self.assertRaisesRegex(UserError, "no emisor RUC"):
            self._import_file(xml)

    def test_import_refuses_missing_clave(self):
        xml = _factura_xml().replace(f"<claveAcceso>{CLAVE}</claveAcceso>", "")
        with self.assertRaisesRegex(UserError, "no clave de acceso"):
            self._import_file(xml)

    def test_import_refuses_no_lines(self):
        xml = _factura_xml(lines=[])
        with self.assertRaisesRegex(UserError, "no detail lines"):
            self._import_file(xml)

    def test_import_refuses_line_without_impuestos(self):
        xml = _factura_xml().replace("<impuestos>", "<otros>")
        xml = xml.replace("</impuestos>", "</otros>")
        with self.assertRaisesRegex(UserError, "no impuestos block"):
            self._import_file(xml)

    def test_import_refuses_mixed_rates_one_line(self):
        xml = _factura_xml()
        mixed_tax = (
            "<codigo>2</codigo><codigoPorcentaje>0</codigoPorcentaje>"
            "<tarifa>0.0</tarifa><baseImponible>10.0</baseImponible>"
            "<valor>0.0</valor>"
        )
        xml = xml.replace(
            "</impuesto></impuestos>",
            f"</impuesto><impuesto>{mixed_tax}</impuesto></impuestos>",
        )
        with self.assertRaisesRegex(UserError, "mixes VAT rates"):
            self._import_file(xml)

    def test_import_refuses_unknown_rate(self):
        with self.assertRaisesRegex(UserError, "No company purchase tax matches"):
            self._import_file(
                _factura_xml(
                    lines=[_line(rate_code="4", rate=30.0)],
                )
            )

    def test_import_refuses_ice_only_line(self):
        with self.assertRaisesRegex(UserError, "ICE/IRBPNR"):
            self._import_file(
                _factura_xml(
                    lines=[_line(tax_code="3", rate_code="0", rate=0.0)],
                )
            )

    def test_import_refuses_reembolsos(self):
        with self.assertRaisesRegex(UserError, "reembolsos"):
            self._import_file(_factura_xml(with_reembolsos=True))

    def test_import_refuses_bad_currency(self):
        with self.assertRaisesRegex(UserError, "US dollars|DOLAR"):
            self._import_file(_factura_xml(currency="EUROS"))

    def test_import_refuses_bad_date(self):
        with self.assertRaisesRegex(UserError, "DD/MM/YYYY"):
            self._import_file(_factura_xml(date="2026-08-15"))

    def test_import_refuses_supplier_name_clash(self):
        self.env["res.partner"].create(
            {
                "name": "ACME SUPPLIER SA",
                "vat": "1313109678001",
                "country_id": self.env.ref("base.ec").id,
            }
        )
        with self.assertRaisesRegex(UserError, "different RUC"):
            self._import_file(_factura_xml())

    def test_import_refuses_no_source(self):
        wizard = self.env["l10n.ec.xml.import"].create({})
        with self.assertRaisesRegex(UserError, "Attach the SRI XML"):
            wizard.action_import()

    def test_import_refuses_bad_access_key(self):
        with self.assertRaisesRegex(ValidationError, "49 digits"):
            self.env["l10n.ec.xml.import"].create({"access_key": "123"})
        wizard = self.env["l10n.ec.xml.import"].create({})
        with self.assertRaisesRegex(ValidationError, "49 digits"):
            wizard.write({"access_key": "123"})

    # -- key door (mocked SRI) -------------------------------------------

    def _key_wizard(self, key=CLAVE):
        return self.env["l10n.ec.xml.import"].create({"access_key": key})

    def test_fetch_key_creates_draft_bill(self):
        response = {
            "autorizaciones": {
                "autorizacion": {
                    "estado": "AUTORIZADO",
                    "numeroAutorizacion": AUTH_NUMBER,
                    "comprobante": _factura_xml(),
                }
            }
        }
        with (
            mock.patch.object(
                L10nEcXmlImport,
                "_l10n_ec_request_authorization",
                return_value=response,
            ),
            mock.patch(
                "odoo.addons.l10n_ec_xml_import.wizard.l10n_ec_xml_import."
                "serialize_object",
                side_effect=lambda result, _as_dict: result,
            ),
        ):
            action = self._key_wizard().action_import()
        bill = self.env["account.move"].browse(action["res_id"])
        self.assertEqual(bill.state, "draft")
        self.assertEqual(bill.l10n_latam_document_number, "001-001-000000001")
        self.assertEqual(bill.l10n_ec_electronic_authorization, AUTH_NUMBER)

    def test_fetch_key_refuses_unauthorized(self):
        response = {
            "autorizaciones": {
                "autorizacion": {
                    "estado": "NO AUTORIZADO",
                    "mensajes": {
                        "mensaje": {
                            "tipo": "ERROR",
                            "identificador": "43",
                            "mensaje": "CLAVE YA PROCESADA",
                            "informacionAdicional": "",
                        }
                    },
                }
            }
        }
        with (
            mock.patch.object(
                L10nEcXmlImport,
                "_l10n_ec_request_authorization",
                return_value=response,
            ),
            mock.patch(
                "odoo.addons.l10n_ec_xml_import.wizard.l10n_ec_xml_import."
                "serialize_object",
                side_effect=lambda result, _as_dict: result,
            ),
        ):
            with self.assertRaisesRegex(UserError, "no authorized document"):
                self._key_wizard().action_import()
        self.assertEqual(self._bill_count(), 0)

    def test_fetch_key_refuses_without_client(self):
        with mock.patch.object(
            L10nEcXmlImport, "_l10n_ec_get_auth_client", return_value=None
        ):
            with self.assertRaisesRegex(UserError, "Upload the XML file instead"):
                self._key_wizard().action_import()
        self.assertEqual(self._bill_count(), 0)

    def test_fetch_key_refuses_client_error(self):
        client = mock.Mock()
        client.service.autorizacionComprobante.side_effect = Exception("timeout")
        with mock.patch.object(
            L10nEcXmlImport, "_l10n_ec_get_auth_client", return_value=client
        ):
            with self.assertRaisesRegex(UserError, "did not answer"):
                self._key_wizard().action_import()
        self.assertEqual(self._bill_count(), 0)

    # -- parser edge cases (direct ValueError) ---------------------------

    def test_parse_refuses_envelope_without_comprobante(self):
        xml = (
            "<autorizacion><estado>AUTORIZADO</estado>"
            "<numeroAutorizacion>123</numeroAutorizacion></autorizacion>"
        )
        with self.assertRaisesRegex(ValueError, "no <comprobante>"):
            parse_supplier_xml(xml)

    def test_parse_refuses_comprobante_without_single_document(self):
        xml = (
            "<autorizacion><estado>AUTORIZADO</estado>"
            "<comprobante></comprobante></autorizacion>"
        )
        with self.assertRaisesRegex(ValueError, "no single document"):
            parse_supplier_xml(xml)

    def test_parse_refuses_empty_xml(self):
        with self.assertRaisesRegex(ValueError, "empty"):
            parse_supplier_xml("   ")

    def test_parse_refuses_factura_without_number(self):
        xml = _factura_xml()
        xml = xml.replace("<estab>001</estab>", "")
        xml = xml.replace("<ptoEmi>001</ptoEmi>", "")
        xml = xml.replace("<secuencial>000000001</secuencial>", "")
        with self.assertRaisesRegex(ValueError, "no document number"):
            parse_supplier_xml(xml)

    def test_parse_refuses_factura_without_ruc_tag(self):
        xml = _factura_xml().replace(f"<ruc>{NEW_RUC}</ruc>", "")
        with self.assertRaisesRegex(ValueError, "no emisor RUC"):
            parse_supplier_xml(xml)

    def test_parse_non_numeric_amount_falls_back_to_zero(self):
        xml = _factura_xml().replace(
            "<importeTotal>230.00</importeTotal>",
            "<importeTotal>ABC</importeTotal>",
        )
        self.assertEqual(parse_supplier_xml(xml)["total"], 0.0)

    # -- wizard refusals ---------------------------------------------------

    def test_import_refuses_unreadable_file(self):
        wizard = self.env["l10n.ec.xml.import"].create(
            {
                "xml_file": base64.b64encode(b"\xff\xfe\xfd"),
                "xml_filename": "supplier.xml",
            }
        )
        with self.assertRaisesRegex(UserError, "not a readable XML"):
            wizard.action_import()
        self.assertEqual(self._bill_count(), 0)

    def test_import_refuses_malformed_key_without_sri_call(self):
        wizard = self.env["l10n.ec.xml.import"].new({"access_key": "123"})
        with (
            mock.patch.object(
                L10nEcXmlImport,
                "_l10n_ec_request_authorization",
                side_effect=AssertionError("SRI must not be called"),
            ),
            self.assertRaisesRegex(UserError, "49 digits"),
        ):
            wizard.action_import()
        self.assertEqual(self._bill_count(), 0)

    def test_fetch_key_refuses_empty_response(self):
        with (
            mock.patch.object(
                L10nEcXmlImport,
                "_l10n_ec_request_authorization",
                return_value={},
            ),
            mock.patch(
                "odoo.addons.l10n_ec_xml_import.wizard.l10n_ec_xml_import."
                "serialize_object",
                side_effect=lambda result, _as_dict: result,
            ),
        ):
            with self.assertRaisesRegex(UserError, "no authorized document"):
                self._key_wizard().action_import()
        self.assertEqual(self._bill_count(), 0)

    def test_fetch_key_refuses_authorized_without_body(self):
        response = {
            "autorizaciones": {
                "autorizacion": {
                    "estado": "AUTORIZADO",
                    "numeroAutorizacion": AUTH_NUMBER,
                    "comprobante": "   ",
                }
            }
        }
        with (
            mock.patch.object(
                L10nEcXmlImport,
                "_l10n_ec_request_authorization",
                return_value=response,
            ),
            mock.patch(
                "odoo.addons.l10n_ec_xml_import.wizard.l10n_ec_xml_import."
                "serialize_object",
                side_effect=lambda result, _as_dict: result,
            ),
        ):
            with self.assertRaisesRegex(UserError, "no document"):
                self._key_wizard().action_import()
        self.assertEqual(self._bill_count(), 0)

    def test_import_refuses_non_usd_company(self):
        self.company.write({"currency_id": self.env.ref("base.EUR").id})
        with self.assertRaisesRegex(UserError, "US dollars"):
            self._import_file(_factura_xml())
        self.assertEqual(self._bill_count(), 0)

    def test_import_refuses_impossible_date(self):
        with self.assertRaisesRegex(UserError, "not a real date"):
            self._import_file(_factura_xml(date="15/13/2026"))

    def test_import_refuses_missing_document_type(self):
        env_class = type(self.env)
        real_ref = env_class.ref

        def _fake_ref(inner_self, xml_id, raise_if_not_found=True):
            if xml_id == "l10n_ec.ec_dt_01":
                return inner_self["l10n_latam.document.type"].browse()
            return real_ref(inner_self, xml_id, raise_if_not_found=raise_if_not_found)

        with mock.patch.object(env_class, "ref", _fake_ref):
            with self.assertRaisesRegex(UserError, "Document type 01"):
                self._import_file(_factura_xml())
        self.assertEqual(self._bill_count(), 0)

    def test_import_refuses_supplier_without_name(self):
        with self.assertRaisesRegex(UserError, "with no name"):
            self._import_file(_factura_xml(ruc="1790011226999", name=""))
        self.assertEqual(self._bill_count(), 0)
