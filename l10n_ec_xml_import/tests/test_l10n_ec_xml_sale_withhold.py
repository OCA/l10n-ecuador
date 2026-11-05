"""Import customer retencion (07) XML against OUR sale invoices, by file or key.

The 07 door reuses the same parser envelope and access-key fetch as the
purchase door, but the voucher travels the manual sale-withhold road:
every sustento matches one posted ``out_invoice`` by SRI number with the
07 emisor RUC as customer (Frappe ``import_customer_withholding`` rule),
and ``l10n_ec.wizard.create.sale.withhold`` posts the voucher with its
usual lines, invoice links and reconcile attempt.

The SRI is never touched: key-path tests mock the request at the
wizard boundary and feed plain-dict responses through the real
envelope unwrapping.
"""

import base64

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.l10n_ec_account_edi.tests.test_edi_common import TestL10nECEdiCommon
from odoo.addons.l10n_ec_xml_import.models.sri_xml import parse_sri_xml

CLAVE = ("1234567890" * 5)[:49]
AUTH_NUMBER = ("9876543210" * 5)[:49]
CUSTOMER_RUC = "1313109678001"


def _retencion_xml(
    number="001-001-000000001",
    ruc=CUSTOMER_RUC,
    name="Test Partner RUC",
    clave=CLAVE,
    date="20/08/2026",
    fiscal_period="08/2026",
    sustentos=None,
):
    if sustentos is None:
        sustentos = [
            {
                "doc_code": "01",
                "number": "001-001-000000001",
                "issue_date": "15/08/2026",
                "entries": [
                    {
                        "code": "1",
                        "withholding_code": "303",
                        "base": 100.0,
                        "rate": 10.0,
                        "value": 10.0,
                    },
                    {
                        "code": "2",
                        "withholding_code": "3",
                        "base": 15.0,
                        "rate": 100.0,
                        "value": 15.0,
                    },
                ],
            }
        ]
    docs = "".join(
        (
            "<docSustento>"
            f"<codDocSustento>{item['doc_code']}</codDocSustento>"
            f"<numDocSustento>{item['number'].replace('-', '')}</numDocSustento>"
            f"<fechaEmisionDocSustento>{item['issue_date']}</fechaEmisionDocSustento>"
            "<retenciones>"
            + "".join(
                "<retencion>"
                f"<codigo>{entry['code']}</codigo>"
                f"<codigoRetencion>{entry['withholding_code']}</codigoRetencion>"
                f"<baseImponible>{entry['base']}</baseImponible>"
                f"<porcentajeRetener>{entry['rate']}</porcentajeRetener>"
                f"<valorRetenido>{entry['value']}</valorRetenido>"
                "</retencion>"
                for entry in item["entries"]
            )
            + "</retenciones>"
            "</docSustento>"
        )
        for item in sustentos
    )
    estab, pto, secuencial = number.split("-")
    return f"""<comprobanteRetencion>
  <infoTributaria>
    <ambiente>2</ambiente>
    <razonSocial>{name}</razonSocial>
    <ruc>{ruc}</ruc>
    <claveAcceso>{clave}</claveAcceso>
    <codDoc>07</codDoc>
    <estab>{estab}</estab>
    <ptoEmi>{pto}</ptoEmi>
    <secuencial>{secuencial}</secuencial>
    <dirMatriz>Av. Test 123</dirMatriz>
  </infoTributaria>
  <infoCompRetencion>
    <fechaEmision>{date}</fechaEmision>
    <tipoIdentificacionSujetoRetenido>04</tipoIdentificacionSujetoRetenido>
    <razonSocialSujetoRetenido>OUR COMPANY</razonSocialSujetoRetenido>
    <identificacionSujetoRetenido>1790011226001</identificacionSujetoRetenido>
    <periodoFiscal>{fiscal_period}</periodoFiscal>
  </infoCompRetencion>
  <docsSustento>{docs}</docsSustento>
</comprobanteRetencion>"""


def _envelope_xml(inner, numero_autorizacion=AUTH_NUMBER, estado="AUTORIZADO"):
    return f"""<autorizacion>
  <estado>{estado}</estado>
  <numeroAutorizacion>{numero_autorizacion}</numeroAutorizacion>
  <fechaAutorizacion>21/08/2026 10:00:00</fechaAutorizacion>
  <ambiente>2</ambiente>
  <comprobante><![CDATA[{inner}]]></comprobante>
</autorizacion>"""


@tagged("post_install", "-at_install")
class TestL10nEcXmlSaleWithhold(TestL10nECEdiCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company.write({"currency_id": cls.env.ref("base.USD").id})
        cls.product_a.write({"list_price": 100.0})
        cls.sale_tax = cls.env["account.tax"].search(
            [
                ("company_id", "=", cls.company.id),
                ("type_tax_use", "=", "sale"),
                ("amount", "=", 15.0),
            ],
            limit=1,
        )
        assert cls.sale_tax, "No 15% sale tax in the EC chart"

    def _make_sale_invoice(self, partner=None):
        partner = partner or self.partner_ruc
        if not self.company.l10n_ec_invoice_version:
            self._setup_edi_company_ec()
        invoice = self._l10n_ec_prepare_edi_out_invoice(
            partner=partner, taxes=[self.sale_tax]
        )
        invoice.write({"invoice_date": "2026-08-15"})
        invoice.action_post()
        self.assertTrue(invoice.l10n_latam_document_number)
        return invoice

    def _sale_number(self, invoice):
        return invoice.l10n_latam_document_number

    def _import_file(self, xml_text, **values):
        wizard = self.env["l10n.ec.xml.import"].create(
            {
                "xml_file": base64.b64encode(xml_text.encode("utf-8")),
                "xml_filename": "retencion.xml",
                **values,
            }
        )
        action = wizard.action_import()
        return self.env["account.move"].browse(action["res_id"]), action

    def _withhold_count(self):
        return self.env["account.move"].search_count(
            [
                ("l10n_ec_withholding_type", "=", "sale"),
                ("l10n_latam_internal_type", "=", "withhold"),
                ("company_id", "=", self.company.id),
            ]
        )

    # -- file door ------------------------------------------------------

    def test_import_retencion_creates_links_and_reconciles(self):
        invoice = self._make_sale_invoice()
        xml = _retencion_xml(
            sustentos=[
                {
                    "doc_code": "01",
                    "number": self._sale_number(invoice),
                    "issue_date": "15/08/2026",
                    "entries": [
                        {
                            "code": "1",
                            "withholding_code": "303",
                            "base": 100.0,
                            "rate": 10.0,
                            "value": 10.0,
                        },
                        {
                            "code": "2",
                            "withholding_code": "3",
                            "base": 15.0,
                            "rate": 100.0,
                            "value": 15.0,
                        },
                    ],
                }
            ]
        )
        withhold, action = self._import_file(xml)
        self.assertEqual(withhold.l10n_ec_withholding_type, "sale")
        self.assertEqual(withhold.l10n_latam_internal_type, "withhold")
        self.assertEqual(withhold.state, "posted")
        self.assertEqual(withhold.partner_id, self.partner_ruc)
        self.assertEqual(withhold.ref, "001-001-000000001")
        self.assertEqual(withhold.l10n_ec_electronic_authorization, CLAVE)
        # Same links the manual wizard writes: M2M on the invoice ...
        self.assertIn(withhold.id, invoice.l10n_ec_withhold_ids.ids)
        # ... and one receivable line per invoice carrying the invoice link.
        receivable = withhold.line_ids.filtered(
            lambda line: line.account_id.account_type == "asset_receivable"
            and line.l10n_ec_invoice_withhold_id == invoice
        )
        self.assertEqual(len(receivable), 1)
        self.assertAlmostEqual(abs(receivable.balance), 25.0, places=2)
        # ... reconciled, like the manual wizard attempts.
        self.assertAlmostEqual(invoice.amount_residual, 90.0, places=2)
        self.assertIn(
            receivable,
            invoice.line_ids.matched_credit_ids.credit_move_id,
        )
        attachment = self.env["ir.attachment"].search(
            [("res_model", "=", "account.move"), ("res_id", "=", withhold.id)]
        )
        self.assertEqual(len(attachment), 1)
        self.assertEqual(action["res_model"], "account.move")
        self.assertEqual(action["res_id"], withhold.id)

    def test_import_retencion_envelope_file_uses_auth_number(self):
        invoice = self._make_sale_invoice()
        xml = _envelope_xml(
            _retencion_xml(
                sustentos=[
                    {
                        "doc_code": "01",
                        "number": self._sale_number(invoice),
                        "issue_date": "15/08/2026",
                        "entries": [
                            {
                                "code": "1",
                                "withholding_code": "303",
                                "base": 100.0,
                                "rate": 10.0,
                                "value": 10.0,
                            }
                        ],
                    }
                ]
            )
        )
        withhold, _action = self._import_file(xml)
        self.assertEqual(withhold.l10n_ec_electronic_authorization, AUTH_NUMBER)

    def test_import_retencion_parses_plain_data(self):
        invoice = self._make_sale_invoice()
        parsed = parse_sri_xml(
            _retencion_xml(
                sustentos=[
                    {
                        "doc_code": "01",
                        "number": self._sale_number(invoice),
                        "issue_date": "15/08/2026",
                        "entries": [
                            {
                                "code": "1",
                                "withholding_code": "303",
                                "base": 100.0,
                                "rate": 10.0,
                                "value": 10.0,
                            }
                        ],
                    }
                ]
            )
        )
        self.assertEqual(parsed["kind"], "retencion")
        self.assertEqual(parsed["number"], "001-001-000000001")
        self.assertEqual(parsed["emisor_ruc"], CUSTOMER_RUC)
        self.assertEqual(parsed["issue_date"], "20/08/2026")
        self.assertEqual(len(parsed["docs"]), 1)
        self.assertEqual(
            parsed["docs"][0]["withholdings"][0]["withholding_code"], "303"
        )

    # -- refusals ---------------------------------------------------------

    def test_import_retencion_refuses_mismatch(self):
        self._make_sale_invoice()
        before = self._withhold_count()
        xml = _retencion_xml(
            sustentos=[
                {
                    "doc_code": "01",
                    "number": "001-001-000009999",
                    "issue_date": "15/08/2026",
                    "entries": [
                        {
                            "code": "1",
                            "withholding_code": "303",
                            "base": 100.0,
                            "rate": 10.0,
                            "value": 10.0,
                        }
                    ],
                }
            ]
        )
        with self.assertRaisesRegex(UserError, "Could not match sustento"):
            self._import_file(xml)
        self.assertEqual(self._withhold_count(), before)

    def test_import_retencion_refuses_ruc_mismatch(self):
        invoice = self._make_sale_invoice()
        before = self._withhold_count()
        xml = _retencion_xml(
            ruc="1790011226999",
            name="OTHER CUSTOMER",
            sustentos=[
                {
                    "doc_code": "01",
                    "number": self._sale_number(invoice),
                    "issue_date": "15/08/2026",
                    "entries": [
                        {
                            "code": "1",
                            "withholding_code": "303",
                            "base": 100.0,
                            "rate": 10.0,
                            "value": 10.0,
                        }
                    ],
                }
            ],
        )
        with self.assertRaisesRegex(UserError, "Could not match sustento"):
            self._import_file(xml)
        self.assertEqual(self._withhold_count(), before)

    def test_import_retencion_refuses_duplicate(self):
        invoice = self._make_sale_invoice()
        xml = _retencion_xml(
            sustentos=[
                {
                    "doc_code": "01",
                    "number": self._sale_number(invoice),
                    "issue_date": "15/08/2026",
                    "entries": [
                        {
                            "code": "1",
                            "withholding_code": "303",
                            "base": 100.0,
                            "rate": 10.0,
                            "value": 10.0,
                        }
                    ],
                }
            ]
        )
        withhold, _action = self._import_file(xml)
        before = self._withhold_count()
        with self.assertRaisesRegex(UserError, "already imported"):
            self._import_file(xml)
        self.assertEqual(self._withhold_count(), before)
        self.assertTrue(withhold.exists())

    def test_import_retencion_refuses_duplicate_auth_key(self):
        first = self._make_sale_invoice()
        second = self._make_sale_invoice()
        first_xml = _retencion_xml(
            number="001-001-000000001",
            sustentos=[
                {
                    "doc_code": "01",
                    "number": self._sale_number(first),
                    "issue_date": "15/08/2026",
                    "entries": [
                        {
                            "code": "1",
                            "withholding_code": "303",
                            "base": 100.0,
                            "rate": 10.0,
                            "value": 10.0,
                        }
                    ],
                }
            ],
        )
        self._import_file(first_xml)
        second_xml = _retencion_xml(
            number="001-001-000000002",
            sustentos=[
                {
                    "doc_code": "01",
                    "number": self._sale_number(second),
                    "issue_date": "15/08/2026",
                    "entries": [
                        {
                            "code": "1",
                            "withholding_code": "303",
                            "base": 100.0,
                            "rate": 10.0,
                            "value": 10.0,
                        }
                    ],
                }
            ],
        )
        with self.assertRaisesRegex(UserError, "already imported"):
            self._import_file(second_xml)
        self.assertEqual(self._withhold_count(), 1)

    def test_import_retencion_refuses_unknown_withhold_tax(self):
        invoice = self._make_sale_invoice()
        xml = _retencion_xml(
            sustentos=[
                {
                    "doc_code": "01",
                    "number": self._sale_number(invoice),
                    "issue_date": "15/08/2026",
                    "entries": [
                        {
                            "code": "1",
                            "withholding_code": "999",
                            "base": 100.0,
                            "rate": 99.0,
                            "value": 99.0,
                        }
                    ],
                }
            ]
        )
        with self.assertRaisesRegex(UserError, "No sale withholding tax matches"):
            self._import_file(xml)
        self.assertEqual(self._withhold_count(), 0)

    def test_import_retencion_refuses_unsupported_impuesto(self):
        invoice = self._make_sale_invoice()
        xml = _retencion_xml(
            sustentos=[
                {
                    "doc_code": "01",
                    "number": self._sale_number(invoice),
                    "issue_date": "15/08/2026",
                    "entries": [
                        {
                            "code": "9",
                            "withholding_code": "500",
                            "base": 100.0,
                            "rate": 5.0,
                            "value": 5.0,
                        }
                    ],
                }
            ]
        )
        with self.assertRaisesRegex(UserError, "no sale voucher slot"):
            self._import_file(xml)
        self.assertEqual(self._withhold_count(), 0)

    def test_import_retencion_refuses_draft_invoice(self):
        partner = self.partner_ruc
        draft = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "company_id": self.company.id,
                "partner_id": partner.id,
                "invoice_date": "2026-08-15",
                "l10n_latam_document_number": "001-001-000000099",
                "invoice_line_ids": [
                    (
                        0,
                        0,
                        {
                            "name": "Widget",
                            "quantity": 1.0,
                            "price_unit": 100.0,
                            "tax_ids": [(6, 0, self.sale_tax.ids)],
                        },
                    )
                ],
            }
        )
        self.assertEqual(draft.state, "draft")
        xml = _retencion_xml(
            sustentos=[
                {
                    "doc_code": "01",
                    "number": "001-001-000000099",
                    "issue_date": "15/08/2026",
                    "entries": [
                        {
                            "code": "1",
                            "withholding_code": "303",
                            "base": 100.0,
                            "rate": 10.0,
                            "value": 10.0,
                        }
                    ],
                }
            ]
        )
        with self.assertRaisesRegex(UserError, "Could not match sustento"):
            self._import_file(xml)
        self.assertEqual(self._withhold_count(), 0)

    def test_import_refuses_non_factura_non_retencion(self):
        credit_note = _retencion_xml().replace(
            "comprobanteRetencion>", "notaCredito>", 10
        )
        with self.assertRaisesRegex(UserError, "Only supplier facturas"):
            self._import_file(credit_note)
        self.assertEqual(self._withhold_count(), 0)

    def test_parse_refuses_retencion_without_sustentos(self):
        xml = _retencion_xml(sustentos=[])
        with self.assertRaisesRegex(ValueError, "no sustento documents"):
            parse_sri_xml(xml)

    def test_parse_refuses_sustento_without_number(self):
        xml = _retencion_xml(
            sustentos=[
                {
                    "doc_code": "01",
                    "number": "",
                    "issue_date": "15/08/2026",
                    "entries": [
                        {
                            "code": "1",
                            "withholding_code": "303",
                            "base": 100.0,
                            "rate": 10.0,
                            "value": 10.0,
                        }
                    ],
                }
            ]
        )
        with self.assertRaisesRegex(ValueError, "without document number"):
            parse_sri_xml(xml)
