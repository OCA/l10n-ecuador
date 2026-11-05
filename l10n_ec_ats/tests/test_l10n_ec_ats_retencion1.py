"""The ``compras`` withholding-document group (``estabRetencion1`` … ``fechaEmiRet1``).

RED first: every test below fails before the collector learns to read the
posted purchase withholding (07), the builder learns to emit the group, and
the validators learn the all-five-or-none rule.
"""

from datetime import date

from lxml import etree

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.account.tests.common import AccountTestInvoicingCommon

from ..builder import ATS_COMPRAS_SPEC, build_ats_xml
from ..schema import validate_ats_xml
from ..validators import (
    AtsPeriod,
    CatalogReader,
    validate_compras_row,
)
from .test_ats_form_base import TestL10nEcAtsFormBase

PERIOD = (date(2016, 3, 1), date(2016, 3, 31))

#: Distinguishes "no date given, fall back to the bill's date" from an
#: explicit ``None`` meaning NULL in the column (no date at all).
_UNSET = object()

WITHHOLD_NUMBER = "001-002-000000001"
WITHHOLD_AUTH = "1234567890123"
WITHHOLD_ISSUE = date(2016, 3, 5)

RETENCION1_FIELDS = (
    "estabRetencion1",
    "ptoEmiRetencion1",
    "secRetencion1",
    "autRetencion1",
    "fechaEmiRet1",
)


@tagged("post_install_l10n", "post_install", "-at_install")
class TestComprasRetencion1Collector(TestL10nEcAtsFormBase):
    """The collector reads the purchase-side 07 already in the database."""

    @classmethod
    @AccountTestInvoicingCommon.setup_country("ec")
    @AccountTestInvoicingCommon.setup_chart_template("ec")
    def setUpClass(cls):
        super().setUpClass()
        cls.Collector = cls.env["l10n.ec.ats.collector"]
        cls.chart_template = cls.env["account.chart.template"].with_company(cls.company)
        cls.journal_purchase = cls.company_data["default_journal_purchase"]
        cls.journal_purchase.write(
            {
                "l10n_ec_emission_address_id": cls.partner_contact.id,
                "l10n_ec_sri_payment_id": cls.env.ref("l10n_ec.P1").id,
                "l10n_latam_use_documents": True,
                "l10n_ec_entity": "001",
                "l10n_ec_emission": "001",
            }
        )
        cls.journal_purchase_withhold = cls.chart_template.ref("purchase_withhold_ec")
        cls.journal_purchase_withhold.l10n_ec_emission_address_id = (
            cls.partner_contact.id
        )
        cls.tax_withhold_profit_303 = cls.chart_template.ref("tax_withhold_profit_303")
        cls._ensure_multiple_suitable_journals()

    def _next_document_number(self, journal):
        journal.ensure_one()
        self._document_sequence = getattr(self, "_document_sequence", 0) + 1
        return "{}-{}-{:09d}".format(
            journal.l10n_ec_entity or "001",
            journal.l10n_ec_emission or "001",
            self._document_sequence,
        )

    def _create_bill(self, **kwargs):
        posting_date = kwargs.pop("posting_date", PERIOD[0])
        emission_date = kwargs.pop("emission_date", None) or posting_date
        document_number = kwargs.pop(
            "document_number", None
        ) or self._next_document_number(self.journal_purchase)
        invoice = self._l10n_ec_create_in_invoice(
            self.partner_ruc,
            journal=self.journal_purchase,
            latam_document_type=self.env.ref("l10n_ec.ec_dt_01"),
            auto_post=False,
            l10n_latam_document_number=document_number,
        )
        invoice.write(
            {
                "date": posting_date,
                "invoice_date": emission_date,
                "l10n_ec_tax_support": "01",
            }
        )
        invoice.action_post()
        invoice.l10n_ec_electronic_authorization = "123456789012"
        return invoice

    def _setup_company_for_withholding(self):
        self._setup_company_ec()
        self.certificate.action_validate_and_load()
        self.company.write(
            {
                "l10n_ec_type_environment": "test",
                "l10n_ec_key_type_id": self.certificate.id,
                "l10n_ec_invoice_version": "1.1.0",
            }
        )
        self.journal_purchase_withhold.l10n_ec_emission_address_id = (
            self.partner_contact.id
        )

    def _set_withholding_document(
        self, withhold, *, number, authorization, invoice_date, move_date
    ):
        """Write the 07's identifying values straight to the column.

        ``l10n_latam_document_number`` is a non-stored compute off ``name``,
        so there is no column to write it to; the ORM inverse would write
        ``name`` before posting, but posting runs the journal sequence and
        recomputes it away. It is therefore written the way this module's
        fixtures already write ``l10n_ec_tax_support`` when the ORM says no:
        flush the pending writes, run the UPDATE on the stored ``name`` (with
        the document type's own prefix, exactly as the inverse would lay it
        out), invalidate the cache, and re-read, so the collector sees exactly
        what a real record would carry. ``None`` means NULL: no date at all,
        no authorization.
        """
        prefix = withhold.l10n_latam_document_type_id.doc_code_prefix
        name = f"{prefix} {number}" if number else "/"
        assignments = [
            "name = %s",
            "l10n_ec_electronic_authorization = %s",
            "invoice_date = %s",
        ]
        params = [name, authorization, invoice_date]
        if move_date is not None:
            assignments.append('"date" = %s')
            params.append(move_date)
        withhold.flush_recordset()
        self.env.cr.execute(
            "UPDATE account_move SET " + ", ".join(assignments) + " WHERE id = %s",
            (*params, withhold.id),
        )
        withhold.invalidate_recordset(
            [
                "name",
                "l10n_latam_document_number",
                "l10n_ec_electronic_authorization",
                "invoice_date",
                "display_name",
            ]
        )
        if move_date is None:
            # ``date`` is NOT NULL and a stored compute that restores today
            # on recompute, so a dateless 07 cannot be written to the column
            # at all; hold it empty in cache instead, without invalidating
            # (which would recompute it back). The collector reads the
            # record, so it sees exactly the "no date at all" state the
            # refusal rule names.
            self.env.cache.set(withhold, withhold._fields["date"], False)

    def _create_withholding(
        self,
        bill,
        tax,
        *,
        number=WITHHOLD_NUMBER,
        authorization=WITHHOLD_AUTH,
        invoice_date=WITHHOLD_ISSUE,
        move_date=_UNSET,
    ):
        self._setup_company_for_withholding()
        base = abs(bill.amount_untaxed_signed)
        lines = []
        for tax_data in tax.compute_all(base).get("taxes", []):
            amount = abs(tax_data.get("base"))
            lines.append(
                (
                    0,
                    0,
                    {
                        "partner_id": bill.partner_id.id,
                        "quantity": 1.0,
                        "price_unit": amount,
                        "account_id": tax_data.get("account_id"),
                        "name": "RET test basis",
                        "debit": amount,
                        "credit": 0.0,
                        "tax_ids": [(6, 0, tax.ids)],
                        "display_type": "product",
                        "l10n_ec_invoice_withhold_id": bill.id,
                        "l10n_ec_tax_support": "01",
                    },
                )
            )
            lines.append(
                (
                    0,
                    0,
                    {
                        "partner_id": bill.partner_id.id,
                        "quantity": 1.0,
                        "price_unit": amount,
                        "account_id": tax_data.get("account_id"),
                        "name": "Counterpart RET",
                        "debit": 0.0,
                        "credit": amount,
                        "tax_ids": [],
                    },
                )
            )
        withholding = self.env["account.move"].create(
            {
                "journal_id": self.journal_purchase_withhold.id,
                "date": bill.date,
                "move_type": "entry",
                "partner_id": bill.partner_id.id,
                "ref": "RET-TEST-0001",
                "l10n_latam_document_type_id": self.env.ref("l10n_ec.ec_dt_07").id,
                "l10n_ec_withholding_type": "purchase",
                "line_ids": lines,
            }
        )
        withholding._post()
        self._set_withholding_document(
            withholding,
            number=number,
            authorization=authorization,
            invoice_date=invoice_date,
            move_date=bill.date if move_date is _UNSET else move_date,
        )
        bill.l10n_ec_withhold_ids = [(4, withholding.id)]
        return withholding

    def _collect(self, period=PERIOD):
        return self.Collector.collect_compras_with_errors(
            self.company, period[0], period[1]
        )

    def _header(self):
        return {
            "TipoIDInformante": "R",
            "IdInformante": "1791311225001",
            "razonSocial": "COMERCIAL ANDINA SA",
            "Anio": 2016,
            "Mes": "03",
            "codigoOperativo": "IVA",
        }

    def _detalle_of(self, document):
        return etree.fromstring(document.encode("utf-8")).find("compras/detalleCompras")

    def test_retencion1_single_07_emits_all_five(self):
        bill = self._create_bill(document_number="001-001-000000101")
        self._create_withholding(bill, self.tax_withhold_profit_303)
        rows, errors = self._collect()
        self.assertFalse(errors, errors)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["estabRetencion1"], "001")
        self.assertEqual(row["ptoEmiRetencion1"], "002")
        self.assertEqual(row["secRetencion1"], "000000001")
        self.assertEqual(row["autRetencion1"], WITHHOLD_AUTH)
        self.assertEqual(row["fechaEmiRet1"], "05/03/2016")

    def test_retencion1_collected_row_builds_schema_valid_xml(self):
        """The collected row parses back with the group carrying the 07's values."""
        bill = self._create_bill(document_number="001-001-000000106")
        self._create_withholding(bill, self.tax_withhold_profit_303)
        rows, errors = self._collect()
        self.assertFalse(errors, errors)
        document = build_ats_xml(
            {
                "header": self._header(),
                "compras": rows,
                "ventas": [],
                "ventasEstablecimiento": [],
                "anulados": [],
            }
        )
        result = validate_ats_xml(document)
        self.assertTrue(result.is_valid, result.errors)
        detalle = self._detalle_of(document)
        self.assertEqual(detalle.findtext("estabRetencion1"), "001")
        self.assertEqual(detalle.findtext("ptoEmiRetencion1"), "002")
        self.assertEqual(detalle.findtext("secRetencion1"), "000000001")
        self.assertEqual(detalle.findtext("autRetencion1"), WITHHOLD_AUTH)
        self.assertEqual(detalle.findtext("fechaEmiRet1"), "05/03/2016")
        names = [child.tag for child in detalle]
        self.assertEqual(
            [name for name in names if name in RETENCION1_FIELDS],
            list(RETENCION1_FIELDS),
        )

    def test_retencion1_absent_from_tree_when_no_withholding(self):
        """No 07 means no group: the parsed tree carries none of the five."""
        self._create_bill(document_number="001-001-000000102")
        rows, errors = self._collect()
        self.assertFalse(errors, errors)
        self.assertEqual(len(rows), 1)
        for field in RETENCION1_FIELDS:
            self.assertNotIn(field, rows[0])
        document = build_ats_xml(
            {
                "header": self._header(),
                "compras": rows,
                "ventas": [],
                "ventasEstablecimiento": [],
                "anulados": [],
            }
        )
        self.assertTrue(validate_ats_xml(document).is_valid)
        detalle = self._detalle_of(document)
        for field in RETENCION1_FIELDS:
            self.assertIsNone(detalle.find(field), field)

    def test_retencion1_two_withholdings_are_refused_naming_both(self):
        bill = self._create_bill(document_number="001-001-000000103")
        first = self._create_withholding(
            bill, self.tax_withhold_profit_303, number="001-002-000000011"
        )
        second = self._create_withholding(
            bill, self.tax_withhold_profit_303, number="001-002-000000012"
        )
        rows, errors = self._collect()
        self.assertEqual(rows, [])
        self.assertTrue(errors, "two purchase withholdings must block the row")
        message = " ".join(str(error["message"]) for error in errors)
        self.assertIn("001-002-000000011", message)
        self.assertIn("001-002-000000012", message)
        self.assertNotIn("estabRetencion1", str(rows))
        self.assertTrue({first.id, second.id} <= set(bill.l10n_ec_withhold_ids.ids))

    def test_retencion1_without_authorization_is_refused(self):
        bill = self._create_bill(document_number="001-001-000000104")
        withhold = self._create_withholding(
            bill, self.tax_withhold_profit_303, authorization=None
        )
        self.assertFalse(withhold.l10n_ec_electronic_authorization)
        rows, errors = self._collect()
        self.assertEqual(rows, [])
        self.assertTrue(errors, "a missing autRetencion1 must block the row")
        message = " ".join(str(error["message"]) for error in errors)
        self.assertIn(withhold.l10n_latam_document_number, message)

    def test_retencion1_without_any_date_is_refused(self):
        bill = self._create_bill(document_number="001-001-000000105")
        withhold = self._create_withholding(
            bill,
            self.tax_withhold_profit_303,
            invoice_date=None,
            move_date=None,
        )
        self.assertFalse(withhold.invoice_date)
        self.assertFalse(withhold.date)
        rows, errors = self._collect()
        self.assertEqual(rows, [])
        self.assertTrue(errors, "a missing fechaEmiRet1 must block the row")
        message = " ".join(str(error["message"]) for error in errors)
        self.assertIn(withhold.l10n_latam_document_number, message)


class TestComprasRetencion1Builder(TransactionCase):
    """The builder emits the group in the XSD's own order."""

    def _compras_row(self, **overrides):
        row = {
            "codSustento": "01",
            "tpIdProv": "01",
            "idProv": "1791311225001",
            "tipoComprobante": "01",
            "parteRel": "NO",
            "fechaRegistro": "15/03/2024",
            "establecimiento": "001",
            "puntoEmision": "001",
            "secuencial": "000000001",
            "fechaEmision": "15/03/2024",
            "autorizacion": "123456789012",
            "baseNoGraIva": 0.0,
            "baseImponible": 100.0,
            "baseImpGrav": 0.0,
            "baseImpExe": 0.0,
            "montoIce": 0.0,
            "montoIva": 15.0,
            "valRetBien10": 0.0,
            "valRetServ20": 0.0,
            "valorRetBienes": 0.0,
            "valRetServ50": 0.0,
            "valorRetServicios": 0.0,
            "valRetServ100": 0.0,
        }
        row.update(overrides)
        return row

    def _payload(self, **blocks):
        payload = {
            "header": {
                "TipoIDInformante": "R",
                "IdInformante": "1791311225001",
                "razonSocial": "COMERCIAL ANDINA SA",
                "Anio": 2024,
                "Mes": "03",
                "codigoOperativo": "IVA",
            },
            "compras": [],
            "ventas": [],
            "ventasEstablecimiento": [],
            "anulados": [],
        }
        payload.update(blocks)
        return payload

    def test_builder_emits_the_retencion1_group_in_xsd_order(self):
        row = self._compras_row(
            estabRetencion1="001",
            ptoEmiRetencion1="002",
            secRetencion1="000000001",
            autRetencion1="1234567890123",
            fechaEmiRet1="05/03/2024",
        )
        document = build_ats_xml(self._payload(compras=[row]))
        result = validate_ats_xml(document)
        self.assertTrue(result.is_valid, result.errors)
        detalle = etree.fromstring(document.encode("utf-8")).find(
            "compras/detalleCompras"
        )
        self.assertEqual(detalle.findtext("estabRetencion1"), "001")
        self.assertEqual(detalle.findtext("ptoEmiRetencion1"), "002")
        self.assertEqual(detalle.findtext("secRetencion1"), "000000001")
        self.assertEqual(detalle.findtext("autRetencion1"), "1234567890123")
        self.assertEqual(detalle.findtext("fechaEmiRet1"), "05/03/2024")
        names = [child.tag for child in detalle]
        self.assertEqual(
            [name for name in names if name in RETENCION1_FIELDS],
            list(RETENCION1_FIELDS),
        )
        spec_names = [field.name for field in ATS_COMPRAS_SPEC]
        self.assertLess(
            spec_names.index("air"),
            spec_names.index("estabRetencion1"),
        )
        self.assertLess(
            spec_names.index("fechaEmiRet1"),
            spec_names.index("estabRetencion2"),
        )

    def test_builder_row_without_group_carries_none_of_the_five(self):
        document = build_ats_xml(self._payload(compras=[self._compras_row()]))
        self.assertTrue(validate_ats_xml(document).is_valid)
        detalle = etree.fromstring(document.encode("utf-8")).find(
            "compras/detalleCompras"
        )
        for field in RETENCION1_FIELDS:
            self.assertIsNone(detalle.find(field), field)


class TestComprasRetencion1Validators(TransactionCase):
    """A payload built by another path is refused the same way."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.reader = CatalogReader(cls.env)

    def _row(self, **overrides):
        row = {
            "codSustento": "01",
            "tpIdProv": "01",
            "idProv": "0992301287001",
            "tipoComprobante": "01",
            "parteRel": "NO",
            "fechaRegistro": "10/08/2026",
            "establecimiento": "001",
            "puntoEmision": "001",
            "secuencial": "000000001",
            "fechaEmision": "10/08/2026",
            "autorizacion": "1710034065001",
            "baseNoGraIva": "100.00",
            "baseImponible": "500.00",
            "baseImpGrav": "1000.00",
            "baseImpExe": "0.00",
            "montoIce": "150.00",
            "montoIva": "120.00",
            "valRetBien10": "0.00",
            "valRetServ20": "0.00",
            "valorRetBienes": "0.00",
            "valRetServ50": "0.00",
            "valorRetServicios": "0.00",
            "valRetServ100": "0.00",
            "formasDePago": [{"formaPago": "01"}],
        }
        row.update(overrides)
        return row

    def test_partial_group_is_refused(self):
        row = self._row(estabRetencion1="001", ptoEmiRetencion1="002")
        found = validate_compras_row(row, AtsPeriod(2026, 8), reader=self.reader)
        blocking = [violation for violation in found if violation.blocking]
        self.assertTrue(blocking, "a partial retencion1 group must block")
        message = " ".join(str(violation) for violation in blocking)
        self.assertIn("secRetencion1", message)

    def test_missing_authorization_is_refused(self):
        row = self._row(
            estabRetencion1="001",
            ptoEmiRetencion1="002",
            secRetencion1="000000001",
            fechaEmiRet1="05/08/2026",
        )
        found = validate_compras_row(row, AtsPeriod(2026, 8), reader=self.reader)
        blocking = [violation for violation in found if violation.blocking]
        self.assertTrue(blocking, "a group without autRetencion1 must block")
        message = " ".join(str(violation) for violation in blocking)
        self.assertIn("autRetencion1", message)

    def test_complete_group_is_accepted(self):
        row = self._row(
            estabRetencion1="001",
            ptoEmiRetencion1="002",
            secRetencion1="000000001",
            autRetencion1="1234567890123",
            fechaEmiRet1="05/08/2026",
        )
        found = validate_compras_row(row, AtsPeriod(2026, 8), reader=self.reader)
        retencion = [violation for violation in found if "retencion" in violation.rule]
        self.assertEqual(retencion, [])
