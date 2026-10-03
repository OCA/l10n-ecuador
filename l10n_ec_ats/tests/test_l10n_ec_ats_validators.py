"""The ``Validaciones`` column: the layer ``ats.xsd`` cannot be.

``Catalogo_ATS.xls`` / ``ESQUEMA TIPO 1 Y 2`` column ``J`` carries a validation
rule per field, and those rules are **business** rules, not grammar. The two
layers are not interchangeable and neither is sufficient alone:

* ``ats.xsd`` declares eight enumerations in total and **none** of them is the
  VAT-rate, withholding or document-type catalogue. It also accepts
  ``establecimiento="000"`` and ``puntoEmision="000"`` on exactly the two
  carriers that matter most for ``compras`` and ``anulados``.
* The ``Validaciones`` column states rules no schema can: the RUC check digit,
  the ``2000`` floor on the reported year, the ceiling that ``montoIce`` may not
  pass, the share of ``montoIva`` each IVA withholding is, and the ``USD
  1.000,00`` threshold above which a payment form is mandatory.

So this module is the second layer, and it is deliberately **pure**: it reads a
collector payload and catalogue records and returns violations. It writes
nothing, opens no cursor and holds no registry state, so a rule can be exercised
against a hand-written payload without a company, a chart of accounts or a
document.

**Two severities, because the source states two.** ``ESQUEMA`` row 22 says
``montoIva`` differing from ``baseImpGrav x porcentajeIva`` is *"mensaje de
advertencia"*; the six IVA-withholding rows say their sum exceeding ``montoIva``
is *"la validación es grave"*. Flattening those into one level would either
block a file the SRI accepts or let a file the SRI refuses through, so
:class:`~..validators.AtsViolation` carries ``severity`` and
:func:`~..validators.blocking` separates what stops generation from what does
not.

**No rate is a literal.** Every percentage comes from the SRI catalogue
resolved **for the reported period** through ``_applicable_on``, and every one of
those reads must return exactly one entry: zero is a coverage hole, more than one
is an overlap, and both abort generation naming the table, the code and the
window (§5.6 Level 3, acceptance criterion 7). The code path that would
substitute a default does not exist, which is what makes "no hardcoded values"
enforceable rather than aspirational.
"""

import copy
from datetime import date
from decimal import Decimal

from odoo.tests.common import TransactionCase

from ..validators import (
    ATS_PERIOD_YEAR_FLOOR,
    FORM_PAYO_THRESHOLD,
    RETENTION_TABLA11_CODE,
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    AirConditionalCodes,
    AtsPeriod,
    AtsViolation,
    CatalogReader,
    CatalogResolutionError,
    blocking,
    credit_note_codes,
    iva_rate,
    retention_rate,
    ruc_check_digit,
    ruc_codes,
    validate_ats,
    validate_compras_row,
    validate_estab_codes,
    validate_header,
    validate_ventas_row,
    warnings_of,
)

#: A period the whole loaded catalogue covers, and one that predates the
#: ``Tabla 11`` 10% and 20% rows so the two can be compared.
CURRENT = AtsPeriod(2026, 8)
#: ``Tabla 12`` was in its 14% regime on this day and is in its 12% regime now,
#: so a rate resolved for one and compared against the other is visibly different.
HISTORICAL = AtsPeriod(2016, 6)
#: Before ``Tabla 11`` code 9 and code 10 existed (both from 2015-06-01), so a
#: retention rate lookup for this period finds nothing at all.
BEFORE_TABLA11_CODES_9_AND_10 = AtsPeriod(2015, 3)

#: ``0992301287001`` -- nine-digit body ``099230128``, verified digit ``7`` under
#: the private-company module 11. Worked out by hand in the module docstring of
#: ``validators.py`` and asserted there.
RUC_SOCIEDAD = "0992301287001"
#: ``1768181150001`` -- public entity, verified digit at the ninth position.
RUC_PUBLICA = "1768181150001"
#: Same body, ninth digit altered: the shape is valid, the arithmetic is not.
RUC_BAD_VERIFIER = "0992301287002"
#: A natural person's RUC. ``check_vat_ec`` in core Odoo accepts any 13 decimal
#: digits, and no authoritative artifact states the algorithm for this branch, so
#: ``ruc_check_digit`` must decline rather than guess.
RUC_NATURAL = "1710034065001"


def _compras_row(**overrides):
    """One ``detalleCompras`` row that satisfies every rule in the module.

    ``montoIva`` is 120.00 because ``baseImpGrav`` is 1000.00 at the 12% regime
    ``CURRENT`` resolves to, which is what makes the retention shares (10% and
    20% of 120.00) land on round numbers.
    """
    row = {
        "codSustento": "01",
        "tpIdProv": "01",
        "idProv": RUC_SOCIEDAD,
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


def _ventas_row(**overrides):
    """One ``detalleVentas`` row that satisfies every rule in the module."""
    row = {
        "tpIdCliente": "04",
        "idCliente": RUC_SOCIEDAD,
        "parteRelVtas": "NO",
        "tipoComprobante": "01",
        "tipoEmision": "E",
        "numeroComprobantes": 1,
        "baseNoGraIva": "0.00",
        "baseImponible": "0.00",
        "baseImpGrav": "1000.00",
        "montoIva": "120.00",
        "montoIce": "0.00",
        "valorRetIva": "100.00",
        "valorRetRenta": "0.00",
        "formasDePago": [{"formaPago": "01"}],
    }
    row.update(overrides)
    return row


def _rules(violations):
    return sorted({violation.rule for violation in violations})


def _of(violations, rule):
    return [violation for violation in violations if violation.rule == rule]


class TestValidatorsCommon(TransactionCase):
    """Shared fixtures: a reader over the **loaded** catalogue, nothing created.

    The rates these tests resolve are read from ``data/ats_catalog_11.xml`` and
    ``data/ats_catalog_12.xml``, which the module loads at install. Building a
    rate in a test instead would prove the arithmetic and prove nothing about
    the real table.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.reader = CatalogReader(cls.env)

    def air_codes(self):
        """The dividend and banana ``codRetAir`` groups, as the caller supplies.

        The membership is the caller's because the SRI catalogue carries no
        column saying which concepts require a dividend sub-report -- see the
        module docstring and the ATS-11 report. The validator is handed the
        groups and never holds them.
        """
        return AirConditionalCodes(
            dividend=frozenset({"327", "330", "504A", "504D"}),
            banana=frozenset({"338", "340", "341", "342"}),
        )


class TestTwoSeverities(TestValidatorsCommon):
    """§5.6's two validation levels are not optional: they are different."""

    def test_error_and_warning_are_distinct_severities(self):
        """A warning reports, an error blocks. ``blocking`` is that distinction."""
        warning = AtsViolation(
            severity=SEVERITY_WARNING,
            rule="compras.monto_iva",
            field="montoIva",
            message="differs",
        )
        error = AtsViolation(
            severity=SEVERITY_ERROR,
            rule="compras.retenciones_tope",
            field="valorRetBienes",
            message="above montoIva",
        )
        self.assertEqual(warnings_of([error, warning]), (warning,))
        self.assertEqual(blocking([error, warning]), (error,))

    def test_the_same_number_is_a_warning_on_one_field_and_an_error_on_another(self):
        """``montoIva`` differing is *advertencia*; the retentions summing above
        ``montoIva`` is *grave*, from the very same ``Validaciones`` cell family.

        Both are exercised here against one real payload so the two levels are
        proven from data rather than from a constructor call.
        """
        row = _compras_row(valorRetBienes="200.00")
        found = validate_compras_row(row, CURRENT, reader=self.reader)
        severities = {violation.rule: violation.severity for violation in found}
        self.assertEqual(severities["compras.retenciones_tope"], SEVERITY_ERROR)

        drifted = _compras_row(montoIva="100.00")
        found = validate_compras_row(drifted, CURRENT, reader=self.reader)
        severities = {violation.rule: violation.severity for violation in found}
        self.assertEqual(severities["compras.monto_iva"], SEVERITY_WARNING)

    def test_a_warning_alone_does_not_block_generation(self):
        row = _compras_row(montoIva="119.00", valorRetBien10="0.00")
        found = validate_compras_row(row, CURRENT, reader=self.reader)
        self.assertTrue(found)
        self.assertEqual(blocking(found), ())


class TestRucCheckDigit(TestValidatorsCommon):
    """``IdInformante``: *"RUC: dígito verificador, 13 dígitos numéricos con 001
    al final."*

    ``ats.xsd`` pins the shape and core Odoo's ``check_vat_ec`` pins the length;
    neither does the arithmetic, and the ficha states the requirement without
    publishing the algorithm.
    """

    def test_ruc_check_digit_accepts_a_private_company(self):
        self.assertEqual(ruc_check_digit(RUC_SOCIEDAD), "valid")

    def test_ruc_check_digit_rejects_a_wrong_verifier(self):
        self.assertEqual(ruc_check_digit(RUC_BAD_VERIFIER), "invalid")

    def test_ruc_check_digit_accepts_a_public_entity(self):
        self.assertEqual(ruc_check_digit(RUC_PUBLICA), "valid")

    def test_ruc_check_digit_declines_on_a_branch_it_cannot_verify(self):
        """No source states the natural-person algorithm, so it must not guess.

        A guessed check digit that disagreed with the SRI's would refuse a valid
        taxpayer, which is worse than declining. ``unverifiable`` is the
        honest answer and it produces no violation.
        """
        self.assertEqual(ruc_check_digit(RUC_NATURAL), "unverifiable")

    def test_ruc_check_digit_declines_on_anything_thirteen_digits_is_not(self):
        for value in ("", "123", "0992301287001A", "09923012870010"):
            with self.subTest(value=value):
                self.assertEqual(ruc_check_digit(value), "unverifiable")

    def test_header_identifies_the_informante_ruc(self):
        header = self._header()
        found = validate_header(
            header, CURRENT, [], [{"codEstab": "001", "ventasEstab": "0.00"}]
        )
        self.assertEqual(found, [])

    def test_header_refuses_an_informante_ruc_that_does_not_add_up(self):
        header = self._header(IdInformante=RUC_BAD_VERIFIER)
        rules = _rules(
            validate_header(
                header, CURRENT, [], [{"codEstab": "001", "ventasEstab": "0.00"}]
            )
        )
        self.assertIn("identificacion.ruc", rules)

    def _header(self, **overrides):
        header = {
            "TipoIDInformante": "R",
            "IdInformante": RUC_SOCIEDAD,
            "razonSocial": "COMERCIAL DEL SUR CIA LTDA",
            "Anio": "2026",
            "Mes": "08",
            "numEstabRuc": "001",
            "totalVentas": "0.00",
            "codigoOperativo": "IVA",
        }
        header.update(overrides)
        return header


class TestHeaderRules(TestValidatorsCommon):
    """``anio >= 2000``, ``numEstabRuc > 000`` and the two header reconciliations."""

    def test_anio_below_the_floor_is_refused(self):
        """*"El año debe corresponder a periodos del 2000 en adelante."*"""
        found = self._header_rules(Anio="1999")
        self.assertIn("periodo.anio", _rules(found))
        self.assertEqual(_of(found, "periodo.anio")[0].severity, SEVERITY_ERROR)

    def test_anio_on_the_floor_is_accepted(self):
        self.assertNotIn("periodo.anio", _rules(self._header_rules(Anio="2000")))

    def test_num_estab_ruc_of_000_is_refused(self):
        """§5.4b. ``numEstabRucType`` carries ``minExclusive 000`` so the schema
        agrees, but the ficha says *"debe ser mayor a 000"* and the builder's
        ``no_zero`` is the last gate rather than the first."""
        found = self._header_rules(numEstabRuc="000")
        self.assertIn("periodo.num_estab_ruc_nonzero", _rules(found))

    def test_num_estab_ruc_counts_the_establishment_rows(self):
        """``ventasEstab``: *"Se generan igual número de campos al valor
        registrado en numEstabRuc"*. The XSD cannot count rows, so this is the
        reconciliation that only a validator can make."""
        rows = [{"codEstab": "001", "ventasEstab": "10.00"}]
        found = self._header_rules(ventas_estab=rows, numEstabRuc="002")
        self.assertIn("periodo.num_estab_ruc_recuento", _rules(found))
        found = self._header_rules(ventas_estab=rows, numEstabRuc="001")
        self.assertNotIn("periodo.num_estab_ruc_recuento", _rules(found))

    def test_total_ventas_equals_the_three_bases(self):
        """*"Casillero no editable, debe ser igual a la sumatoria de los valores
        registrados en los campos baseNoGraIva, Base Imponible y baseimpGrav."*"""
        ventas = [_ventas_row(baseNoGraIva="100.00", baseImponible="200.00")]
        found = self._header_rules(ventas=ventas, totalVentas="1299.99")
        self.assertIn("total_ventas.sumatoria", _rules(found))
        found = self._header_rules(ventas=ventas, totalVentas="1300.00")
        self.assertNotIn("total_ventas.sumatoria", _rules(found))

    def test_ventas_estab_may_not_exceed_total_ventas(self):
        """Ficha §2.3: *"La sumatoria del total de ventas por los establecimientos
        no puede ser mayor al valor registrado en el campo total ventas."*"""
        estab = [{"codEstab": "001", "ventasEstab": "1300.01"}]
        found = self._header_rules(ventas_estab=estab, totalVentas="1300.00")
        self.assertIn("ventas_estab.tope", _rules(found))

    def test_ventas_estab_net_below_total_ventas_is_accepted(self):
        """The arithmetic that decides Contradiction A, asserted as behaviour.

        A period with one invoice of 1300.00 and one credit note of 100.00 gives
        ``totalVentas`` 1400.00 -- gross, as the ficha §2.1 defines it, over
        *all* sales -- and ``sum(ventasEstab)`` 1200.00, the net the credit
        note reduces. The ficha's ceiling is satisfied, which is exactly the
        state that is impossible if ``totalVentas`` excluded electronic
        invoices while ``ventasEstab`` did not.
        """
        ventas = [_ventas_row(baseImpGrav="1300.00"), _ventas_row(baseImpGrav="100.00")]
        estab = [{"codEstab": "001", "ventasEstab": "1200.00"}]
        found = self._header_rules(
            ventas=ventas, ventas_estab=estab, totalVentas="1400.00"
        )
        self.assertNotIn("ventas_estab.tope", _rules(found))

    def _header_rules(
        self,
        ventas=(),
        ventas_estab=({"codEstab": "001", "ventasEstab": "0.00"},),
        **overrides,
    ):
        header = {
            "TipoIDInformante": "R",
            "IdInformante": RUC_SOCIEDAD,
            "razonSocial": "COMERCIAL DEL SUR CIA LTDA",
            "Anio": "2026",
            "Mes": "08",
            "numEstabRuc": "001",
            "totalVentas": "0.00",
            "codigoOperativo": "IVA",
        }
        header.update(overrides)
        return validate_header(header, CURRENT, list(ventas), list(ventas_estab))


class TestEstablishmentNeverZero(TestValidatorsCommon):
    """§5.4b, generalised. The XSD accepts ``000`` on the two carriers that
    matter most, so a document carrying one clears every grammar rule and is
    refused at reception."""

    def test_establishment_000_is_refused(self):
        found = validate_estab_codes({"compras": [_compras_row(establecimiento="000")]})
        self.assertEqual([v.rule for v in found], ["establecimiento.no_000"])
        self.assertEqual(found[0].severity, SEVERITY_ERROR)
        self.assertEqual(found[0].field, "establecimiento")

    def test_emission_point_000_is_refused(self):
        found = validate_estab_codes({"compras": [_compras_row(puntoEmision="000")]})
        self.assertEqual([v.field for v in found], ["puntoEmision"])

    def test_the_sweep_reaches_the_anulados_and_establecimiento_blocks(self):
        payload = {
            "anulados": [
                {
                    "tipoComprobante": "01",
                    "establecimiento": "000",
                    "puntoEmision": "001",
                    "secuencialInicio": "000000001",
                    "secuencialFin": "000000001",
                    "autorizacion": "1710034065001",
                }
            ],
            "ventasEstablecimiento": [{"codEstab": "000", "ventasEstab": "0.00"}],
        }
        found = validate_estab_codes(payload)
        self.assertEqual(
            sorted(v.field for v in found), ["codEstab", "establecimiento"]
        )

    def test_the_sweep_reaches_nested_air_and_forma_pago_rows(self):
        row = _compras_row(
            air=[
                {
                    "codRetAir": "343",
                    "baseImpAir": "1.00",
                    "porcentajeAir": "1.00",
                    "valRetAir": "1.00",
                    "ptoEmiRetencion1": "000",
                }
            ]
        )
        found = validate_estab_codes({"compras": [row]})
        self.assertEqual([v.field for v in found], ["ptoEmiRetencion1"])

    def test_a_legal_establishment_is_accepted(self):
        self.assertEqual(validate_estab_codes({"compras": [_compras_row()]}), [])

    def test_a_two_digit_recap_code_is_not_swept(self):
        """``establecimientoRecap`` is ``estRecapType``: two digits, inside the
        Tipo 2 block. ``01`` is legal there and ``000`` is not a value it can
        hold, so a value-driven sweep is safe where a name-driven one is not."""
        self.assertEqual(
            validate_estab_codes({"recap": [{"establecimientoRecap": "01"}]}), []
        )


class TestPurchasesPeriodRules(TestValidatorsCommon):
    """``fechaRegistro`` and ``fechaEmision`` against the reported period."""

    def test_fecha_registro_of_another_period_is_refused(self):
        """*"Debe ser igual al período que informa --> mes - anio, si se registra
        un período diferente es error."*"""
        found = validate_compras_row(
            _compras_row(fechaRegistro="10/07/2026"), CURRENT, reader=self.reader
        )
        self.assertIn("fecha_registro.periodo", _rules(found))
        self.assertEqual(
            _of(found, "fecha_registro.periodo")[0].severity, SEVERITY_ERROR
        )

    def test_fecha_registro_of_the_reported_period_is_accepted(self):
        self.assertNotIn(
            "fecha_registro.periodo",
            _rules(
                validate_compras_row(
                    _compras_row(fechaRegistro="31/08/2026"),
                    CURRENT,
                    reader=self.reader,
                )
            ),
        )

    def test_fecha_emision_after_fecha_registro_is_refused(self):
        found = validate_compras_row(
            _compras_row(fechaEmision="11/08/2026"), CURRENT, reader=self.reader
        )
        self.assertIn("fecha_emision.registro", _rules(found))

    def test_fecha_emision_more_than_a_year_before_registro_is_refused(self):
        """*"Debe estar dentro del vencimiento un año mayor al campo
        fechaEmision"*: the ceiling is one calendar year, not 365 days."""
        found = validate_compras_row(
            _compras_row(fechaRegistro="10/08/2026", fechaEmision="09/08/2025"),
            CURRENT,
            reader=self.reader,
        )
        self.assertIn("fecha_emision.anio", _rules(found))

    def test_fecha_emision_exactly_one_year_before_registro_is_accepted(self):
        self.assertNotIn(
            "fecha_emision.anio",
            _rules(
                validate_compras_row(
                    _compras_row(fechaRegistro="10/08/2026", fechaEmision="10/08/2025"),
                    CURRENT,
                    reader=self.reader,
                )
            ),
        )

    def test_fecha_emision_after_the_reported_period_is_refused(self):
        found = validate_compras_row(
            _compras_row(fechaRegistro="31/08/2026", fechaEmision="31/08/2026"),
            CURRENT,
            reader=self.reader,
        )
        self.assertNotIn("fecha_emision.registro", _rules(found))
        found = validate_compras_row(
            _compras_row(fechaRegistro="31/08/2026", fechaEmision="31/08/2026"),
            AtsPeriod(2026, 7),
            reader=self.reader,
        )
        self.assertIn("fecha_emision.periodo", _rules(found))


class TestPurchasesCeilings(TestValidatorsCommon):
    """``montoIce``, ``baseImpAir`` and ``valRetAir`` against the bases."""

    def test_monto_ice_may_not_exceed_the_bases(self):
        """*"Debe ser menor ó igual a la sumatoria de baseNoGrava,
        baseImponible, baseImpGrav"*"""
        found = validate_compras_row(
            _compras_row(montoIce="1600.01"), CURRENT, reader=self.reader
        )
        self.assertIn("compras.monto_ice", _rules(found))
        found = validate_compras_row(
            _compras_row(montoIce="1600.00"), CURRENT, reader=self.reader
        )
        self.assertNotIn("compras.monto_ice", _rules(found))

    def test_base_imp_air_may_not_exceed_the_bases(self):
        row = _compras_row(
            air=[
                {
                    "codRetAir": "343",
                    "baseImpAir": "1600.01",
                    "porcentajeAir": "1.00",
                    "valRetAir": "16.00",
                }
            ]
        )
        found = validate_compras_row(row, CURRENT, reader=self.reader)
        self.assertIn("compras.base_imp_air", _rules(found))

    def test_base_imp_air_below_the_bases_is_a_warning_not_an_error(self):
        """*"Si es menor a la sumatoria [...] se desplegará mensaje de
        advertencia."*"""
        row = _compras_row(
            air=[
                {
                    "codRetAir": "343",
                    "baseImpAir": "100.00",
                    "porcentajeAir": "1.00",
                    "valRetAir": "1.00",
                }
            ]
        )
        found = validate_compras_row(row, CURRENT, reader=self.reader)
        self.assertEqual(
            _of(found, "compras.base_imp_air_inferior")[0].severity, SEVERITY_WARNING
        )

    def test_val_ret_air_may_not_exceed_base_imp_air(self):
        row = _compras_row(
            air=[
                {
                    "codRetAir": "343",
                    "baseImpAir": "100.00",
                    "porcentajeAir": "1.00",
                    "valRetAir": "100.01",
                }
            ]
        )
        found = validate_compras_row(row, CURRENT, reader=self.reader)
        self.assertIn("compras.val_ret_air", _rules(found))

    def test_val_ret_air_differing_from_the_percentage_is_a_warning(self):
        row = _compras_row(
            air=[
                {
                    "codRetAir": "343",
                    "baseImpAir": "100.00",
                    "porcentajeAir": "1.00",
                    "valRetAir": "50.00",
                }
            ]
        )
        found = validate_compras_row(row, CURRENT, reader=self.reader)
        self.assertEqual(
            _of(found, "compras.val_ret_air_cuota")[0].severity, SEVERITY_WARNING
        )


class TestIvaRetentions(TestValidatorsCommon):
    """The six ``Tabla 11`` shares, and the grave sum.

    The percentages are **resolved from ``Tabla 11`` for the reported period**,
    never read from the prose, so a rate change moves the expectation with the
    data instead of with the code.
    """

    def test_a_zero_retention_is_exempt_from_the_share_check(self):
        """``valRetBien10`` is mandatory and defaults to ``0.00``.

        A purchase line that withheld no IVA carries a zero, and alerting that
        ``0.00`` is not 10% of ``montoIva`` on every ordinary purchase would
        train the reader to ignore alerts. Nothing was withheld, so there is
        nothing to reconcile.
        """
        found = validate_compras_row(_compras_row(), CURRENT, reader=self.reader)
        self.assertNotIn("compras.retencion_iva_cuota", _rules(found))

    def test_every_equality_share_is_checked_against_the_resolved_rate(self):
        row = _compras_row(
            valRetBien10="1.00",
            valRetServ20="2.00",
            valorRetBienes="3.00",
            valorRetServicios="5.00",
        )
        found = validate_compras_row(row, CURRENT, reader=self.reader)
        drift = _of(found, "compras.retencion_iva_cuota")
        self.assertEqual(
            sorted(v.field for v in drift),
            ["valRetBien10", "valRetServ20", "valorRetBienes", "valorRetServicios"],
        )
        self.assertEqual({v.severity for v in drift}, {SEVERITY_WARNING})

    def test_the_exact_share_of_monto_iva_is_accepted(self):
        row = _compras_row(valRetBien10="12.00", valRetServ20="24.00")
        found = validate_compras_row(row, CURRENT, reader=self.reader)
        self.assertNotIn("compras.retencion_iva_cuota", _rules(found))

    def test_the_up_to_fields_accept_less_but_alert_above_the_ceiling(self):
        """``valRetServ50`` says *"hasta el 50%"* and ``valRetServ100`` *"hasta el
        100%"*: a lower share is within the rule, a higher one is not."""
        less = validate_compras_row(
            _compras_row(valRetServ50="1.00", valRetServ100="0.00"),
            CURRENT,
            reader=self.reader,
        )
        self.assertNotIn("compras.retencion_iva_cuota", _rules(less))
        more = validate_compras_row(
            _compras_row(valRetServ50="600.00", valRetServ100="1200.00"),
            CURRENT,
            reader=self.reader,
        )
        drift = _of(more, "compras.retencion_iva_cuota")
        self.assertEqual(
            sorted(v.field for v in drift), ["valRetServ100", "valRetServ50"]
        )
        self.assertEqual({v.severity for v in drift}, {SEVERITY_WARNING})

    def test_the_sum_of_the_retentions_may_not_exceed_monto_iva(self):
        """*"La sumatoria de las Retenciones no puede ser mayor al valor Monto IVA
        generar este mensaje la validación es grave."*"""
        row = _compras_row(valRetBien10="60.00", valorRetBienes="61.00")
        found = validate_compras_row(row, CURRENT, reader=self.reader)
        grave = _of(found, "compras.retenciones_tope")
        self.assertEqual(len(grave), 1)
        self.assertEqual(grave[0].severity, SEVERITY_ERROR)
        self.assertEqual(grave[0].facts["monto_iva"], Decimal("120.00"))
        self.assertEqual(grave[0].facts["suma"], Decimal("121.00"))

    def test_a_sum_exactly_equal_to_monto_iva_is_accepted(self):
        row = _compras_row(valRetBien10="60.00", valorRetBienes="60.00")
        found = validate_compras_row(row, CURRENT, reader=self.reader)
        self.assertNotIn("compras.retenciones_tope", _rules(found))

    def test_each_retention_rate_is_the_catalogue_percentage_not_the_prose(self):
        """The binding element -> ``Tabla 11`` code is pinned against the loaded
        table, so the six percentages these tests rely on are read from
        ``data/ats_catalog_11.xml`` and not asserted in this file."""
        self.assertEqual(
            sorted(
                {
                    retention_rate(self.reader, field, CURRENT.catalog_probe)
                    for field in RETENTION_TABLA11_CODE
                }
            ),
            sorted(
                [
                    Decimal("10"),
                    Decimal("20"),
                    Decimal("30"),
                    Decimal("50"),
                    Decimal("70"),
                    Decimal("100"),
                ]
            ),
        )


class TestMontoIva(TestValidatorsCommon):
    """``montoIva = baseImpGrav x porcentajeIva`` from ``Tabla 12``, an *alerta*."""

    def test_monto_iva_differing_from_the_product_is_a_warning(self):
        found = validate_compras_row(
            _compras_row(montoIva="100.00"), CURRENT, reader=self.reader
        )
        drift = _of(found, "compras.monto_iva")
        self.assertEqual(len(drift), 1)
        self.assertEqual(drift[0].severity, SEVERITY_WARNING)
        self.assertEqual(drift[0].facts["esperado"], Decimal("120.00"))

    def test_monto_iva_above_base_imp_grav_is_an_error(self):
        """*"No debe ser mayor a baseImpGrav"*, in the same cell as the warning
        and stated as a prohibition rather than an alert."""
        found = validate_compras_row(
            _compras_row(baseImpGrav="100.00", montoIva="120.00"),
            CURRENT,
            reader=self.reader,
        )
        self.assertEqual(
            _of(found, "compras.monto_iva_tope")[0].severity, SEVERITY_ERROR
        )

    def test_the_rate_follows_the_reported_period(self):
        """``Tabla 12`` was at 14% in June 2016 and is at 12% now, so the same
        base expects two different amounts. Acceptance criterion 8, one layer
        down."""
        self.assertEqual(iva_rate(self.reader, HISTORICAL.catalog_probe), Decimal("14"))
        self.assertEqual(iva_rate(self.reader, CURRENT.catalog_probe), Decimal("12"))
        found = validate_compras_row(
            _compras_row(baseImpGrav="1000.00", montoIva="140.00"),
            HISTORICAL,
            reader=self.reader,
        )
        self.assertNotIn("compras.monto_iva", _rules(found))
        found = validate_compras_row(
            _compras_row(baseImpGrav="1000.00", montoIva="140.00"),
            CURRENT,
            reader=self.reader,
        )
        self.assertIn("compras.monto_iva", _rules(found))


class TestValorRetIva(TestValidatorsCommon):
    """``valorRetIva = baseImpGrav x porcentajeIva`` from ``Tabla 11``, and
    *"el valor puede ser mayor o igual"*: ``0.00`` is sanctioned, a value
    matching no single share in force is an alerta, and there is no grave branch
    left on this field."""

    def test_a_zero_retention_against_a_taxed_base_is_not_a_finding(self):
        """*"Si no existe valor colocar 0.00"* -- the cell says so to file.

        There is no withholding to reconcile, so there is no product to disagree
        with and ``0.00`` produces **no violation at all**. The base is a taxed
        ``1000.00`` on purpose: against a zero base a clean result would prove
        nothing, because zero would be the only arithmetically possible answer.

        This is the case a floor reading refuses. *"El valor puede ser mayor o
        igual"* read as a lower bound turns the cell's own ``0.00`` into an
        error on **every sale whose client withheld nothing** -- most sales -- so
        the company could not file a sales period at all and the message would
        blame the company rather than the rule.
        """
        found = validate_ventas_row(
            _ventas_row(baseImpGrav="1000.00", valorRetIva="0.00"),
            CURRENT,
            reader=self.reader,
        )
        self.assertNotIn("ventas.valor_ret_iva", _rules(found))
        # Asserted on the whole row, not on the one rule: an exemption proved by
        # "the rule we care about is quiet" is also satisfied by a second,
        # unrelated finding masking it.
        self.assertEqual(_rules(found), [])

    def test_another_single_rate_share_is_accepted(self):
        """The row aggregates every withholding for one client and document
        type, so a higher published rate is not a difference."""
        self.assertNotIn(
            "ventas.valor_ret_iva",
            _rules(
                validate_ventas_row(
                    _ventas_row(valorRetIva="200.00"), CURRENT, reader=self.reader
                )
            ),
        )

    def test_a_value_matching_no_single_rate_share_is_a_warning(self):
        violation = _of(
            validate_ventas_row(
                _ventas_row(valorRetIva="150.00"), CURRENT, reader=self.reader
            ),
            "ventas.valor_ret_iva",
        )[0]
        self.assertEqual(violation.severity, SEVERITY_WARNING)

    def test_the_ten_percent_share_is_accepted(self):
        self.assertNotIn(
            "ventas.valor_ret_iva",
            _rules(
                validate_ventas_row(
                    _ventas_row(valorRetIva="100.00"), CURRENT, reader=self.reader
                )
            ),
        )


class TestSalesRules(TestValidatorsCommon):
    """``ventas``-side reconciliations, on the block the collector aggregates."""

    def test_monto_ice_may_not_exceed_base_imp_grav(self):
        found = validate_ventas_row(
            _ventas_row(montoIce="1000.01"), CURRENT, reader=self.reader
        )
        self.assertIn("ventas.monto_ice", _rules(found))

    def test_monto_iva_differing_from_the_product_is_a_warning(self):
        drift = [
            v
            for v in validate_ventas_row(
                _ventas_row(montoIva="1.00"), CURRENT, reader=self.reader
            )
            if v.rule == "ventas.monto_iva"
        ]
        self.assertEqual(drift[0].severity, SEVERITY_WARNING)


class TestFormaPago(TestValidatorsCommon):
    """``formaPago`` mandatory above **USD 1.000,00**, and multi-valued."""

    def test_forma_pago_is_mandatory_above_the_threshold(self):
        row = _compras_row(formasDePago=[])
        found = validate_compras_row(row, CURRENT, reader=self.reader)
        violation = _of(found, "compras.forma_pago_obligatoria")[0]
        self.assertEqual(violation.severity, SEVERITY_ERROR)
        self.assertEqual(violation.facts["umbral"], FORM_PAYO_THRESHOLD)

    def test_exactly_the_threshold_does_not_make_it_mandatory(self):
        """*"mayor a USD 1.000,00"* -- equal is not greater."""
        row = _compras_row(
            baseNoGraIva="0.00",
            baseImponible="0.00",
            baseImpGrav="1000.00",
            montoIce="0.00",
            montoIva="0.00",
            formasDePago=[],
        )
        found = validate_compras_row(row, CURRENT, reader=self.reader)
        self.assertNotIn("compras.forma_pago_obligatoria", _rules(found))

    def test_one_cent_over_the_threshold_makes_it_mandatory(self):
        row = _compras_row(
            baseNoGraIva="0.00",
            baseImponible="0.00",
            baseImpGrav="1000.01",
            montoIce="0.00",
            montoIva="0.00",
            formasDePago=[],
        )
        found = validate_compras_row(row, CURRENT, reader=self.reader)
        self.assertIn("compras.forma_pago_obligatoria", _rules(found))

    def test_a_credit_note_carries_no_payment_form(self):
        """*"No aplica para los tipos de comprobantes Notas de Crédito (04)."*

        The document types are read from ``Tabla 4`` by the phrase the sheet
        spells them with, so no code is held here -- and the test walks
        **every** code the catalogue calls a credit note rather than asserting
        one literal, which is the point of resolving it.
        """
        credit = credit_note_codes(self.reader, CURRENT.catalog_probe)
        self.assertTrue(credit, "no Tabla 4 row is called a credit note")
        for code in sorted(credit):
            with self.subTest(codigo=code):
                row = _compras_row(formasDePago=[], tipoComprobante=code)
                found = validate_compras_row(row, CURRENT, reader=self.reader)
                self.assertNotIn("compras.forma_pago_obligatoria", _rules(found))

    def test_a_credit_note_still_permits_a_payment_form(self):
        """The exemption removes the obligation, not the capability."""
        credit = sorted(credit_note_codes(self.reader, CURRENT.catalog_probe))[0]
        row = _compras_row(formasDePago=[{"formaPago": "01"}], tipoComprobante=credit)
        found = validate_compras_row(row, CURRENT, reader=self.reader)
        self.assertNotIn("compras.forma_pago_obligatoria", _rules(found))

    def test_more_than_one_payment_form_is_allowed(self):
        """*"debe permitir ingresar mas de una forma de pago por cada
        transacción"*: the collection is a list, and a list of two is a month
        with two payment forms, not a duplicate."""
        row = _compras_row(formasDePago=[{"formaPago": "01"}, {"formaPago": "17"}])
        found = validate_compras_row(row, CURRENT, reader=self.reader)
        self.assertNotIn("compras.forma_pago_duplicada", _rules(found))

    def test_the_same_payment_form_twice_is_refused(self):
        """``formaPagoType`` is a ``simpleType`` with ``maxOccurs="unbounded"``, so
        the schema accepts the duplicate and cannot mean it is legal."""
        row = _compras_row(formasDePago=[{"formaPago": "01"}, {"formaPago": "01"}])
        found = validate_compras_row(row, CURRENT, reader=self.reader)
        violation = _of(found, "compras.forma_pago_duplicada")[0]
        self.assertEqual(violation.severity, SEVERITY_ERROR)


class TestCatalogResolution(TestValidatorsCommon):
    """§5.6 Level 3 and acceptance criterion 7: exactly one entry, or abort."""

    def test_zero_entries_abort_naming_the_table_the_code_and_the_window(self):
        with self.assertRaises(CatalogResolutionError) as caught:
            retention_rate(
                self.reader, "valRetBien10", BEFORE_TABLA11_CODES_9_AND_10.catalog_probe
            )
        message = str(caught.exception)
        self.assertIn("11", message)
        self.assertIn("9", message)
        self.assertIn("2015-03", message)
        self.assertEqual(caught.exception.found, 0)
        self.assertEqual(caught.exception.code, "9")

    def test_more_than_one_entry_aborts_naming_the_table_the_code_and_the_window(self):
        table = self.env["l10n.ec.ats.catalog.table"].search(
            [("code", "=", "12")], limit=1
        )
        self.env["l10n.ec.ats.catalog.entry"].create(
            {
                "table_id": table.id,
                "code": "12",
                "percentage": 12.0,
                "date_start": "2017-06-01",
            }
        )
        with self.assertRaises(CatalogResolutionError) as caught:
            iva_rate(self.reader, CURRENT.catalog_probe)
        message = str(caught.exception)
        self.assertIn("12", message)
        self.assertIn("12", message)
        self.assertEqual(caught.exception.found, 2)
        self.assertIn("2026-08", message)

    def test_the_read_goes_through_applicable_on_not_a_flat_search(self):
        """A rate that changed must resolve to the one in force, not the newest.

        ``Tabla 12`` code ``12`` covers three separate windows. Reading the table
        without the period would find three entries and abort; resolving for the
        period finds one.
        """
        reader = CatalogReader(self.env)
        entries = reader.by_table("12", CURRENT.catalog_probe)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries.percentage, 12.0)

    def test_a_historical_period_resolves_the_regime_that_was_in_force(self):
        entries = CatalogReader(self.env).by_table("12", HISTORICAL.catalog_probe)
        self.assertEqual(entries.percentage, 14.0)


class TestConditionalEmission(TestValidatorsCommon):
    """``numCajBan`` / ``precCajBan`` for the banana codes, ``fechaPagoDiv`` /
    ``imRentaSoc`` / ``anioUtDiv`` for the dividend codes.

    The membership is **not** held here: the SRI catalogue carries no column
    saying which concepts require which sub-report, so the caller supplies the
    groups and the validator is handed them.
    """

    def test_a_dividend_field_on_a_dividend_code_is_accepted(self):
        found = validate_compras_row(
            _compras_row(
                air=[
                    {
                        "codRetAir": "327",
                        "baseImpAir": "100.00",
                        "porcentajeAir": "10.00",
                        "valRetAir": "10.00",
                        "fechaPagoDiv": "31/08/2026",
                        "anioUtDiv": "2026",
                    }
                ]
            ),
            CURRENT,
            reader=self.reader,
            air_codes=self.air_codes(),
        )
        self.assertNotIn("air.emision_condicional", _rules(found))

    def test_a_dividend_field_on_another_code_is_refused(self):
        found = validate_compras_row(
            _compras_row(
                air=[
                    {
                        "codRetAir": "343",
                        "baseImpAir": "100.00",
                        "porcentajeAir": "1.00",
                        "valRetAir": "1.00",
                        "fechaPagoDiv": "31/08/2026",
                    }
                ]
            ),
            CURRENT,
            reader=self.reader,
            air_codes=self.air_codes(),
        )
        violation = _of(found, "air.emision_condicional")[0]
        self.assertEqual(violation.severity, SEVERITY_ERROR)
        self.assertEqual(violation.field, "fechaPagoDiv")

    def test_a_banana_field_on_another_code_is_refused(self):
        found = validate_compras_row(
            _compras_row(
                air=[
                    {
                        "codRetAir": "343",
                        "baseImpAir": "100.00",
                        "porcentajeAir": "1.00",
                        "valRetAir": "1.00",
                        "precCajBan": "5000.00",
                    }
                ]
            ),
            CURRENT,
            reader=self.reader,
            air_codes=self.air_codes(),
        )
        violation = _of(found, "air.emision_condicional")[0]
        self.assertEqual(violation.field, "precCajBan")

    def test_the_dividend_payment_date_may_not_be_after_the_period(self):
        found = validate_compras_row(
            _compras_row(
                air=[
                    {
                        "codRetAir": "327",
                        "baseImpAir": "100.00",
                        "porcentajeAir": "10.00",
                        "valRetAir": "10.00",
                        "fechaPagoDiv": "01/09/2026",
                    }
                ]
            ),
            CURRENT,
            reader=self.reader,
            air_codes=self.air_codes(),
        )
        self.assertIn("air.fecha_pago_div", _rules(found))

    def test_the_dividend_year_may_not_be_after_the_reported_year(self):
        found = validate_compras_row(
            _compras_row(
                air=[
                    {
                        "codRetAir": "327",
                        "baseImpAir": "100.00",
                        "porcentajeAir": "10.00",
                        "valRetAir": "10.00",
                        "anioUtDiv": "2027",
                    }
                ]
            ),
            CURRENT,
            reader=self.reader,
            air_codes=self.air_codes(),
        )
        self.assertIn("air.anio_ut_div", _rules(found))

    def test_an_air_row_carrying_a_conditional_field_without_the_seam_raises(self):
        """A silent skip would file an ``air`` block nobody checked.

        The seam is missing and a conditional element is present, so the
        validator says so instead of passing.
        """
        with self.assertRaises(ValueError) as caught:
            validate_compras_row(
                _compras_row(
                    air=[
                        {
                            "codRetAir": "343",
                            "baseImpAir": "1.00",
                            "porcentajeAir": "1.00",
                            "valRetAir": "1.00",
                            "fechaPagoDiv": "31/08/2026",
                        }
                    ]
                ),
                CURRENT,
                reader=self.reader,
            )
        self.assertIn("air_codes", str(caught.exception))

    def test_an_air_row_with_no_conditional_field_needs_no_seam(self):
        """Refusing every ``air`` row would block ordinary income withholdings,
        which the five conditional elements say nothing about."""
        found = validate_compras_row(
            _compras_row(
                air=[
                    {
                        "codRetAir": "343",
                        "baseImpAir": "1.00",
                        "porcentajeAir": "1.00",
                        "valRetAir": "1.00",
                    }
                ]
            ),
            CURRENT,
            reader=self.reader,
        )
        self.assertNotIn("air.emision_condicional", _rules(found))


class TestPurity(TestValidatorsCommon):
    """§6: a validator that rewrites its input is not a validator."""

    def test_validate_ats_does_not_mutate_the_payload(self):
        # The header is keyed "header", the one key ``ats_header`` resolves. It
        # carries deliberately bad values so the header rules actually fire: a
        # mutation check that never reads the header cannot catch a rewriter
        # living there.
        payload = {
            "header": {
                "TipoIDInformante": "R",
                "IdInformante": RUC_BAD_VERIFIER,
                "razonSocial": "COMERCIAL DEL SUR CIA LTDA",
                "Anio": "1999",
                "Mes": "08",
                "numEstabRuc": "000",
                "totalVentas": "0.00",
                "codigoOperativo": "IVA",
            },
            "compras": [
                _compras_row(
                    establecimiento="000",
                    fechaRegistro="10/07/2026",
                    montoIva="119.00",
                    valorRetBienes="500.00",
                    air=[
                        {
                            "codRetAir": "343",
                            "baseImpAir": "99999.00",
                            "porcentajeAir": "1.00",
                            "valRetAir": "1.00",
                        }
                    ],
                )
            ],
            "ventas": [_ventas_row(valorRetIva="0.01")],
            "ventasEstablecimiento": [{"codEstab": "000", "ventasEstab": "0.00"}],
            "anulados": [],
        }
        snapshot = copy.deepcopy(payload)
        found = validate_ats(payload, CURRENT, env=self.env, air_codes=self.air_codes())
        self.assertTrue(found)
        self.assertEqual(payload, snapshot)

    def test_validate_ats_does_not_mutate_a_list_in_place(self):
        """The list is the part a ``.append`` would touch, so it is asserted on
        its own rather than through the whole-payload equality above."""
        payload = {"compras": [_compras_row()]}
        compras = payload["compras"]
        before = list(compras)
        validate_ats(payload, CURRENT, env=self.env)
        self.assertEqual(compras, before)
        self.assertEqual(len(compras), 1)

    def test_the_violations_carry_the_facts_they_assert(self):
        payload = {
            "compras": [_compras_row(valRetBien10="60.00", valorRetBienes="61.00")]
        }
        found = validate_ats(payload, CURRENT, env=self.env)
        grave = [v for v in found if v.rule == "compras.retenciones_tope"][0]
        self.assertEqual(grave.facts["suma"], Decimal("121.00"))
        self.assertEqual(grave.facts["monto_iva"], Decimal("120.00"))
        self.assertIn("valorRetBienes", str(grave))


class TestAggregate(TestValidatorsCommon):
    """``validate_ats`` walks every in-scope block once."""

    def test_a_clean_payload_reports_nothing(self):
        """``[]`` from a fully-populated header is a verdict, not a non-event.

        Every rule in :func:`~..validators.validate_header` is
        **presence-guarded** -- behind ``if declared_anio:``, ``if num_estab:``,
        ``if "totalVentas" in header`` -- so an **absent** header satisfies all of
        them trivially and returns the identical ``[]``. A clean-payload test
        written against a header the aggregator never read is therefore green for
        a reason that has nothing to do with the payload being clean, and it stays
        green when the header stops being read at all.

        The second half of the test is what makes the first half mean something:
        the *same* payload with one header scalar broken must report, so the rules
        demonstrably ran over real content.
        """
        payload = {
            "header": {
                "TipoIDInformante": "R",
                "IdInformante": RUC_SOCIEDAD,
                "razonSocial": "COMERCIAL DEL SUR CIA LTDA",
                "Anio": "2026",
                "Mes": "08",
                "regimenMicroempresa": "SI",
                "numEstabRuc": "001",
                "totalVentas": "1000.00",
                "codigoOperativo": "IVA",
            },
            "compras": [_compras_row(valRetBien10="12.00", valRetServ20="24.00")],
            "ventas": [_ventas_row()],
            "ventasEstablecimiento": [{"codEstab": "001", "ventasEstab": "1000.00"}],
            "anulados": [
                {
                    "tipoComprobante": "01",
                    "establecimiento": "001",
                    "puntoEmision": "001",
                    "secuencialInicio": "000000005",
                    "secuencialFin": "000000005",
                    "autorizacion": "1710034065001",
                }
            ],
        }
        self.assertEqual(validate_ats(payload, CURRENT, env=self.env), [])

        broken = copy.deepcopy(payload)
        broken["header"]["numEstabRuc"] = "002"
        self.assertIn(
            "periodo.num_estab_ruc_recuento",
            _rules(validate_ats(broken, CURRENT, env=self.env)),
        )

    def test_a_broken_informante_ruc_in_the_header_block_is_reported(self):
        """The recurrence guard: the header block is genuinely walked.

        **Why this test exists.** ``validate_ats`` and ``build_ats_xml`` once read
        the header under different keys -- the builder from ``header``, the
        validator from ``iva``, the element name. Every rule in
        :func:`~..validators.validate_header`, ``IdInformante``'s RUC check digit
        among them, was then evaluated against an **empty** mapping. Because every
        one of those rules is presence-guarded, an empty header is not a loud
        failure: it is a clean run. The suite stayed green, and the suite was
        wrong -- it asserted that a block nobody read produced nothing, which is
        what an unwalked block always produces.

        So the regression to catch is not "a header rule misbehaves". It is
        **"the header stopped being read and the presence guards hid it"**, and
        only a test that *expects a violation* can catch it: a payload valid in
        every respect except a deliberately broken ``IdInformante`` verifier must
        report ``identificacion.ruc``. If the header is skipped, this returns
        ``[]`` and fails.

        It goes through :func:`~..validators.validate_ats`, **not**
        :func:`~..validators.validate_header` directly, on purpose. The unit tests
        of ``validate_header`` passed throughout the regression -- they handed it
        the header as an argument -- so only a test that lets the aggregator pick
        the key can observe the two layers disagreeing.
        """
        payload = {
            "header": {
                "TipoIDInformante": "R",
                # Same nine-digit body as RUC_SOCIEDAD, verifier altered to 2: the
                # shape is valid, the module 11 is not.
                "IdInformante": RUC_BAD_VERIFIER,
                "razonSocial": "COMERCIAL DEL SUR CIA LTDA",
                "Anio": "2026",
                "Mes": "08",
                "regimenMicroempresa": "SI",
                "numEstabRuc": "001",
                "totalVentas": "0.00",
                "codigoOperativo": "IVA",
            },
            "ventasEstablecimiento": [{"codEstab": "001", "ventasEstab": "0.00"}],
        }
        found = validate_ats(payload, CURRENT, env=self.env)
        self.assertEqual(_rules(found), ["identificacion.ruc"])
        # And the breach is blocking, not advisory: an informante RUC that does not
        # add up is a grave finding, so generation must stop.
        self.assertEqual(blocking(found), tuple(found))

    def test_every_block_is_walked(self):
        payload = {
            "header": {
                "Anio": "1999",
                "numEstabRuc": "000",
                "totalVentas": "1.00",
                "IdInformante": RUC_SOCIEDAD,
                "Mes": "08",
                "TipoIDInformante": "R",
                "razonSocial": "COMERCIAL DEL SUR CIA LTDA",
                "codigoOperativo": "IVA",
            },
            "compras": [_compras_row(establecimiento="000")],
            "ventas": [_ventas_row(valorRetIva="0.01")],
            "ventasEstablecimiento": [{"codEstab": "000", "ventasEstab": "0.00"}],
        }
        found = validate_ats(payload, CURRENT, env=self.env)
        self.assertEqual(
            _rules(found),
            [
                "establecimiento.no_000",
                "periodo.anio",
                "periodo.cabecera",
                "periodo.num_estab_ruc_nonzero",
                "total_ventas.sumatoria",
                "ventas.valor_ret_iva",
            ],
        )

    def test_a_sequential_range_of_one_document_is_accepted(self):
        """Contradiction B, asserted as behaviour rather than as prose.

        ``ESQUEMA`` says ``secuencialFin`` *"debe ser mayor a
        secuencialInicio"*; ficha §2.5 says *"Para anular un solo comprobante,
        se debe indicar este número en ambos campos"*. Equality is the only
        value that can express the case the ficha describes, so a range of one
        must validate.
        """
        payload = {
            "header": {
                "TipoIDInformante": "R",
                "IdInformante": RUC_SOCIEDAD,
                "razonSocial": "COMERCIAL DEL SUR CIA LTDA",
                "Anio": "2026",
                "Mes": "08",
                "regimenMicroempresa": "SI",
                "numEstabRuc": "001",
                "totalVentas": "0.00",
                "codigoOperativo": "IVA",
            },
            "ventasEstablecimiento": [{"codEstab": "001", "ventasEstab": "0.00"}],
            "anulados": [
                {
                    "tipoComprobante": "01",
                    "establecimiento": "001",
                    "puntoEmision": "001",
                    "secuencialInicio": "000000005",
                    "secuencialFin": "000000005",
                    "autorizacion": "1710034065001",
                }
            ],
        }
        self.assertEqual(validate_ats(payload, CURRENT, env=self.env), [])

        # The header in *this* payload is live rather than absent, so the [] above
        # is a verdict on a real block: there are no ventas rows, so any non-zero
        # totalVentas is a sumatoria mismatch and nothing else can fire.
        broken = copy.deepcopy(payload)
        broken["header"]["totalVentas"] = "0.01"
        self.assertEqual(
            _rules(validate_ats(broken, CURRENT, env=self.env)),
            ["total_ventas.sumatoria"],
        )

    def test_the_period_floor_constant_is_the_one_the_cell_states(self):
        self.assertEqual(ATS_PERIOD_YEAR_FLOOR, 2000)

    def test_the_reader_is_reusable_across_periods(self):
        first = CatalogReader(self.env).by_table("12", HISTORICAL.catalog_probe)
        second = CatalogReader(self.env).by_table("12", CURRENT.catalog_probe)
        self.assertEqual(first.percentage, 14.0)
        self.assertEqual(second.percentage, 12.0)

    def test_the_period_carries_the_day_the_catalogue_is_probed_on(self):
        self.assertEqual(CURRENT.catalog_probe, date(2026, 8, 31))
        self.assertEqual(HISTORICAL.catalog_probe, date(2016, 6, 30))
        self.assertEqual(CURRENT.first_day, date(2026, 8, 1))
        self.assertEqual(CURRENT.last_day, date(2026, 8, 31))


class TestTriangulation(TestValidatorsCommon):
    """The cases that decide whether a rule fires **for the stated reason**.

    A rule that fires for a neighbouring reason still passes a test written on
    the failure, so each one here isolates the rule it names: every other input
    is one that would fire a different rule if the implementation were wrong.
    """

    def test_an_absent_monto_iva_is_not_a_reconciliation_failure(self):
        """*"Si no existe valor colocar 0.00"* is a filing default, not a check.

        A row with no taxable base and no ``montoIva`` reconciles ``0.00``
        against ``0.00`` and nothing fires. Treating the absence as a difference
        would turn every row the collectors legitimately omit into an error. The
        companion is that a row **with** a taxable base and no ``montoIva`` does
        fire, because then the reconciliation has a real gap to report.
        """
        row = _compras_row(baseImpGrav="0.00")
        del row["montoIva"]
        found = validate_compras_row(row, CURRENT, reader=self.reader)
        self.assertNotIn("compras.monto_iva", _rules(found))
        self.assertNotIn("compras.monto_iva_tope", _rules(found))
        with_base = _compras_row()
        del with_base["montoIva"]
        self.assertIn(
            "compras.monto_iva",
            _rules(validate_compras_row(with_base, CURRENT, reader=self.reader)),
        )

    def test_an_absent_total_ventas_skips_both_header_reconciliations(self):
        """``totalVentas`` is ``minOccurs="0"``, so an absent header field is a
        legal document and there is nothing to reconcile."""
        found = validate_header(
            {"Anio": "2026", "Mes": "08", "IdInformante": RUC_SOCIEDAD},
            CURRENT,
            [_ventas_row()],
            [{"codEstab": "001", "ventasEstab": "1000.00"}],
        )
        self.assertNotIn("total_ventas.sumatoria", _rules(found))
        self.assertNotIn("ventas_estab.tope", _rules(found))

    def test_an_absent_num_estab_ruc_skips_the_count_reconciliation(self):
        """Same reason: an omitted header field is not a mismatch."""
        found = validate_header(
            {"Anio": "2026", "Mes": "08", "IdInformante": RUC_SOCIEDAD},
            CURRENT,
            [],
            [{"codEstab": "001", "ventasEstab": "0.00"}],
        )
        self.assertNotIn("periodo.num_estab_ruc_recuento", _rules(found))
        self.assertNotIn("periodo.num_estab_ruc_nonzero", _rules(found))

    def test_an_identification_type_the_catalogue_calls_a_cedula_is_not_checked(self):
        """``idProv`` states one branch **per** identification type.

        ``Tabla 2`` code ``02`` is ``COMPRA - CEDULA``, a ten-digit document with
        its own digit, and running the RUC module 11 over it would refuse a valid
        supplier.
        """
        rucs = ruc_codes(self.reader, CURRENT.catalog_probe)
        cedula = sorted(
            entry.code
            for entry in self.reader.by_table("02", CURRENT.catalog_probe)
            if entry.code not in rucs
        )[0]
        row = _compras_row(tpIdProv=cedula, idProv="1710034065")
        found = validate_compras_row(row, CURRENT, reader=self.reader)
        self.assertNotIn("identificacion.ruc", _rules(found))

    def test_a_client_ruc_is_checked_and_a_client_cedula_is_not(self):
        """``idCliente`` states the same per-type branches ``idProv`` does.

        ``Tabla 2`` code ``04`` is ``VENTA - RUC`` and carries the module 11;
        code ``07`` is ``VENTA - CONSUMIDOR FINAL``, which the cell sizes at 13
        characters with no digit, and must not be run through one.
        """
        rucs = ruc_codes(self.reader, CURRENT.catalog_probe)
        non_ruc = sorted(
            entry.code
            for entry in self.reader.by_table("02", CURRENT.catalog_probe)
            if entry.code not in rucs and entry.description
        )[0]
        self.assertIn(
            "identificacion.ruc",
            _rules(
                validate_ventas_row(
                    _ventas_row(idCliente=RUC_BAD_VERIFIER), CURRENT, reader=self.reader
                )
            ),
        )
        self.assertNotIn(
            "identificacion.ruc",
            _rules(
                validate_ventas_row(
                    _ventas_row(tpIdCliente=non_ruc, idCliente="1710034065"),
                    CURRENT,
                    reader=self.reader,
                )
            ),
        )

    def test_the_identification_branch_follows_the_reported_period(self):
        """``Tabla 2`` code ``09`` (``EXPORTACION``) expired on 2015-02-28 and
        code ``20`` (``EXPORTACION - RUC``) opened on 2015-03-01.

        Resolving the identification types on the wrong day would pick the
        expired row or the new one, so the branch a row takes depends on the
        period being filed.
        """
        before = ruc_codes(self.reader, AtsPeriod(2015, 2).catalog_probe)
        after = ruc_codes(self.reader, AtsPeriod(2015, 3).catalog_probe)
        self.assertIn("20", after)
        self.assertNotIn("20", before)
        self.assertIn("01", before)
        self.assertIn("01", after)

    def test_the_zero_retention_exemption_does_not_disable_the_sum_check(self):
        """A single non-zero share above ``montoIva`` is still grave.

        The exemption is on the **share** check, not on the total, so exempting
        zeros must not turn off the one rule the cell calls grave.
        """
        row = _compras_row(valorRetServicios="121.00")
        found = validate_compras_row(row, CURRENT, reader=self.reader)
        self.assertEqual(
            _of(found, "compras.retenciones_tope")[0].severity, SEVERITY_ERROR
        )

    def test_the_accepted_valor_ret_iva_shares_follow_the_reported_period(self):
        """What survives of the removed floor is **temporality**: which shares are
        accepted depends on the period being filed, not on a constant.

        ``Tabla 11`` code ``11`` (50%) opened on 2016-01-01. So the *same*
        declared ``valorRetIva`` of ``500.00`` on the *same* base of ``1000.00``
        is the cell's own product in 2026 and matches no share at all in 2015-03.
        A flat share set -- one resolved on any single day, or a literal -- would
        give both periods the same answer and pass a filing the SRI would not.

        The two accepted sets are then read from the rule's own reconciliation
        data, so the claim is about the sets and not about one hand-picked value.
        """
        fifty_percent = _ventas_row(valorRetIva="500.00")

        self.assertNotIn(
            "ventas.valor_ret_iva",
            _rules(validate_ventas_row(fifty_percent, CURRENT, reader=self.reader)),
        )
        self.assertIn(
            "ventas.valor_ret_iva",
            _rules(
                validate_ventas_row(
                    fifty_percent,
                    BEFORE_TABLA11_CODES_9_AND_10,
                    reader=self.reader,
                )
            ),
        )

        def accepted_shares(period):
            return _of(
                validate_ventas_row(
                    _ventas_row(valorRetIva="150.00"), period, reader=self.reader
                ),
                "ventas.valor_ret_iva",
            )[0].facts["declared_shares"]

        old_shares = accepted_shares(BEFORE_TABLA11_CODES_9_AND_10)
        new_shares = accepted_shares(CURRENT)
        self.assertEqual(
            old_shares, [Decimal("300.00"), Decimal("700.00"), Decimal("1000.00")]
        )
        self.assertEqual(
            new_shares,
            [
                Decimal("100.00"),
                Decimal("200.00"),
                Decimal("300.00"),
                Decimal("500.00"),
                Decimal("700.00"),
                Decimal("1000.00"),
            ],
        )
        self.assertNotEqual(old_shares, new_shares)

    def test_a_cent_over_a_share_is_a_difference_and_a_cent_under_is_not(self):
        """The comparison is on two decimals, which is what the document carries.

        A binary float would make ``12.00`` and the share differ by a fraction of
        a cent and fire an alerta on a correct file.
        """
        exact = validate_compras_row(
            _compras_row(valRetBien10="12.00"), CURRENT, reader=self.reader
        )
        self.assertNotIn("compras.retencion_iva_cuota", _rules(exact))
        over = validate_compras_row(
            _compras_row(valRetBien10="12.01"), CURRENT, reader=self.reader
        )
        self.assertIn("compras.retencion_iva_cuota", _rules(over))

    def test_a_second_establishment_changes_neither_the_ceiling_nor_the_count(self):
        """``ventasEstab`` reconciles as a **sum**, so splitting it in two rows
        must not change the answer."""
        one = validate_header(
            self._header(totalVentas="1200.00"),
            CURRENT,
            [_ventas_row(baseImpGrav="1200.00")],
            [{"codEstab": "001", "ventasEstab": "1200.00"}],
        )
        two = validate_header(
            self._header(numEstabRuc="002", totalVentas="1200.00"),
            CURRENT,
            [_ventas_row(baseImpGrav="1200.00")],
            [
                {"codEstab": "001", "ventasEstab": "700.00"},
                {"codEstab": "002", "ventasEstab": "500.00"},
            ],
        )
        self.assertEqual(_rules(one), _rules(two))
        self.assertEqual(_rules(one), [])

    def test_the_establishment_sweep_compares_the_three_character_string(self):
        """``"000"`` is the only value the rule refuses, and it is a **string**.

        A payload carrying ``0`` is a different defect: ``establecimientoType`` is
        ``[0-9]{3}``, so the builder refuses the one-character value on its
        lexical pattern before this layer ever sees it. Widening the comparison to
        the integer ``0`` here would report a rule the builder already caught and
        would hide which one actually rejected the document.
        """
        self.assertEqual(
            validate_estab_codes({"compras": [{"establecimiento": 0}]}), []
        )
        found = validate_estab_codes({"compras": [{"establecimiento": "000"}]})
        self.assertEqual(
            [(v.field, v.where) for v in found],
            [("establecimiento", "compras[0].establecimiento")],
        )

    def test_a_conditional_element_on_its_own_code_does_not_also_alert(self):
        """``air.emision_condicional`` and the period rules are independent.

        A dividend row with a late ``fechaPagoDiv`` must report the date and
        nothing else, or a reviewer cannot tell which rule rejected it.
        """
        found = validate_compras_row(
            _compras_row(
                air=[
                    {
                        "codRetAir": "330",
                        "baseImpAir": "1600.00",
                        "porcentajeAir": "1.00",
                        "valRetAir": "16.00",
                        "fechaPagoDiv": "01/09/2026",
                    }
                ]
            ),
            CURRENT,
            reader=self.reader,
            air_codes=self.air_codes(),
        )
        self.assertEqual(_rules(found), ["air.fecha_pago_div"])

    def test_blocking_and_warnings_partition_the_whole_report(self):
        """``blocking`` and ``warnings_of`` must be complementary and exhaustive,
        so a caller cannot accidentally ignore one severity by filtering on the
        other."""
        found = validate_compras_row(
            _compras_row(montoIva="119.00", valRetBien10="119.01"),
            CURRENT,
            reader=self.reader,
        )
        self.assertTrue(blocking(found))
        self.assertTrue(warnings_of(found))
        self.assertEqual(len(blocking(found)) + len(warnings_of(found)), len(found))
        self.assertEqual(
            {v.rule for v in blocking(found)}, {"compras.retenciones_tope"}
        )

    def _header(self, **overrides):
        header = {
            "TipoIDInformante": "R",
            "IdInformante": RUC_SOCIEDAD,
            "razonSocial": "COMERCIAL DEL SUR CIA LTDA",
            "Anio": "2026",
            "Mes": "08",
            "numEstabRuc": "001",
            "totalVentas": "0.00",
            "codigoOperativo": "IVA",
        }
        header.update(overrides)
        return header
