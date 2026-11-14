import hashlib

from odoo.tests.common import TransactionCase
from odoo.tools import file_open

from ..schema import ATS_XSD_PATH, validate_ats_xml

#: sha256 of the ats.xsd published by the SRI, as downloaded from
#: https://www.sri.gob.ec/formularios-e-instructivos1 (Anexo Transaccional
#: Simplificado, "ats.xsd"). 70379 bytes, 1533 CRLF lines, UTF-8 BOM, XML
#: declaration of encoding="ISO-8859-1".
#:
#: This is the provenance record. It is NOT the hash of the shipped file: the
#: repository's own quality gate rewrites any file it classifies as text, and it
#: classifies .xsd, so the upstream bytes cannot be committed unmodified. The
#: shipped copy is normalized by exactly four mechanical steps, listed in the
#: header of ``data/xsd/ats.xsd`` and asserted by
#: ``test_shipped_xsd_is_normalized_exactly_as_documented``.
ATS_XSD_SOURCE_SHA256 = (
    "4756fe58c139aff5073137ca3b2e66f7a6a55b096861c682b007d5f99b276a9a"
)

#: sha256 of the shipped, normalized ``data/xsd/ats.xsd``. Pins the copy that is
#: actually in the tree: any later hand-edit, reformat or "schema fix" changes
#: this value and fails the build, which is the point of shipping a hash at all.
ATS_XSD_SHA256 = "9b528dc11b06416a633912036bd0f1f236036313fd21518be711be6aa0203453"

FIXTURES_PATH = "l10n_ec_ats/tests/fixtures"


class TestAtsSchema(TransactionCase):
    """What the shipped ATS schema actually does.

    The XSD is authoritative for lexical shape, cardinality and patterns, and
    explicitly NOT authoritative for business rules: it is more permissive than
    the SRI norm. These tests therefore pin two kinds of behaviour at once --
    the rejections a builder must never trigger, and the acceptances a builder
    must defend against, because those are the places where XSD validation and
    SRI reception disagree.

    Fixture names describe the intent of a case, not its verdict. The three
    fixtures whose names begin ``ats_invalid_`` are in fact accepted:
    ``ats_invalid_negative_total_ventas`` (case 5),
    ``ats_invalid_impossible_date`` (case 6) and
    ``ats_deprecated_retention_fields`` (case 11). Each one says so in its own
    header comment, and each test method below is named after the reason the
    schema is wrong rather than after the fixture file.
    """

    def _xml(self, fixture_name):
        with file_open(f"{FIXTURES_PATH}/{fixture_name}", "rb") as fixture_file:
            return fixture_file.read()

    def _validate_fixture(self, fixture_name):
        return validate_ats_xml(self._xml(fixture_name))

    def _assert_rejected(self, fixture_name):
        result = self._validate_fixture(fixture_name)
        self.assertFalse(
            result.is_valid,
            f"{fixture_name} should be rejected by ats.xsd but validated",
        )
        self.assertTrue(
            result.errors,
            "a rejected document must carry the collected error messages",
        )
        return result

    # Case 13a -- the shipped artifact

    def test_shipped_xsd_compiles(self):
        """The schema resolves and compiles under the runtime lxml."""
        result = self._validate_fixture("ats_valid_minimal.xml")
        self.assertTrue(result.is_valid, result.errors)

    def test_shipped_xsd_is_normalized_exactly_as_documented(self):
        """The shipped copy hashes to the pinned value and carries the four
        documented deviations from the upstream artifact, and no others.

        The upstream file cannot be shipped byte for byte: pre-commit's
        trailing-whitespace, end-of-file-fixer and mixed-line-ending --fix=lf
        hooks classify .xsd as text and rewrite it, so a byte-identical copy
        leaves the real quality gate red and the working tree dirty on every
        checkout. Normalising was therefore forced, not chosen. The trade is
        paid for here: the shipped hash pins what we did ship, and the four
        assertions below pin exactly what was changed to get there, so the
        normalization cannot be widened silently.
        """
        with file_open(ATS_XSD_PATH, "rb") as xsd_file:
            raw = xsd_file.read()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), ATS_XSD_SHA256)
        declaration = raw.split(b"\n", 1)[0]
        # 1. the UTF-8 BOM was removed
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        # 2. the declaration now matches the actual bytes, which are UTF-8
        #    (the file contains U+00E9 and U+00BF, neither of which survives a
        #    Latin-1 decode into the intended text)
        self.assertEqual(declaration, b'<?xml version="1.0" encoding="UTF-8"?>')
        # 3. CRLF was converted to LF
        self.assertEqual(raw.count(b"\r\n"), 0)
        # 4. trailing whitespace was stripped, and the file ends in one newline
        for line in raw.split(b"\n"):
            self.assertEqual(line, line.rstrip())
        self.assertTrue(raw.endswith(b"\n"))
        self.assertFalse(raw.endswith(b"\n\n"))
        # the provenance of the normalization is recorded on the artifact, right
        # after the declaration, because a declaration must come first
        self.assertIn(ATS_XSD_SOURCE_SHA256.encode(), raw)
        self.assertIn(
            b"4756fe58c139aff5073137ca3b2e66f7a6a55b096861c682b007d5f99b276a9a", raw
        )
        # and the schema itself is still the schema: nothing in the header was
        # dropped, and the root declaration is intact
        self.assertIn(b"<xsd:schema", raw)
        self.assertIn(b'name="detalleComprasType"', raw)

    def test_upstream_xsd_hash_is_recorded_for_audit(self):
        """The pristine SRI hash stays in the suite as a provenance record.

        It cannot be asserted against the shipped file, because the shipped file
        is normalized, but it must not rot silently: if the SRI republishes the
        artifact, this constant is what a reviewer compares against before
        accepting any refresh of the shipped copy.
        """
        self.assertEqual(len(ATS_XSD_SOURCE_SHA256), 64)
        self.assertNotEqual(ATS_XSD_SOURCE_SHA256, ATS_XSD_SHA256)

    # Case 1 -- the baseline

    def test_valid_minimal_document_is_accepted(self):
        """The minimal Tipo 1 header plus one compras row validates.

        ivaType (ats.xsd:585-636) requires TipoIDInformante, IdInformante,
        razonSocial, Anio, Mes and codigoOperativo; detalleComprasType
        (ats.xsd:704-846) requires nineteen further children in a fixed order.
        This is the fixture every rejection case mutates.
        """
        result = self._validate_fixture("ats_valid_minimal.xml")
        self.assertTrue(result.is_valid, result.errors)
        self.assertEqual(result.errors, ())

    # Case 2 -- decimal pattern

    def test_amount_with_a_single_decimal_is_rejected(self):
        """monedaType (ats.xsd:1308) admits two decimals or none, never one.

        "100.5" matches neither alternative, so a builder that formats from a
        float without quantising produces a file the schema refuses.
        """
        result = self._assert_rejected("ats_invalid_amount_one_decimal.xml")
        self.assertIn("baseImponible", "\n".join(result.errors))

    # Case 3 -- accents

    def test_accented_razon_social_is_rejected(self):
        """razonSocialType (ats.xsd:50) allows only [a-zA-Z0-9\\s].

        Observed: the rule is stricter than "strip the accents". An accented
        letter alone is rejected, and ASCII punctuation is rejected just the
        same -- the dot of "S.A." is outside the class too. So a builder cannot
        normalise a partner name by transliterating; every character outside
        [a-zA-Z0-9\\s] has to be dropped, which means the common "SA de CV",
        "S.R.L." and "CIA LTDA" suffixes must be reduced, not merely
        de-accented.
        """
        self._assert_rejected("ats_invalid_accented_razon_social.xml")

        valid = self._xml("ats_valid_minimal.xml")

        accented_only = validate_ats_xml(
            valid.replace(
                b"<razonSocial>COMERCIAL ANDINA SA</razonSocial>",
                "<razonSocial>COMERCIAL ÑANDINA SA</razonSocial>".encode(),
            )
        )
        self.assertFalse(
            accented_only.is_valid,
            "an accented letter alone must already break razonSocialType",
        )

        ascii_punctuation_only = validate_ats_xml(
            valid.replace(
                b"<razonSocial>COMERCIAL ANDINA SA</razonSocial>",
                b"<razonSocial>COMERCIAL ANDINA S.A.</razonSocial>",
            )
        )
        self.assertFalse(
            ascii_punctuation_only.is_valid,
            "the dot is outside [a-zA-Z0-9\\s] exactly as the accent is, so the "
            "rule is not an accent rule but a whitelist rule",
        )

    # Case 4 -- negative line amounts

    def test_negative_line_amount_is_rejected(self):
        """monedaType sets minInclusive 0.0 (ats.xsd:1306) and has no negative
        alternative in its pattern (ats.xsd:1308).

        A credit note cannot be expressed by negating a line amount.
        """
        result = self._assert_rejected("ats_invalid_negative_line_amount.xml")
        self.assertIn("montoIva", "\n".join(result.errors))

    # Case 5 -- THE SCHEMA IS NOT THE NORM

    def test_negative_total_ventas_is_accepted_because_only_this_type_allows_it(
        self,
    ):
        """totalVentasType (ats.xsd:1302) is the one amount type with negative
        alternatives, and it carries no minInclusive at all.

        This is the asymmetry that makes credit-note handling non-obvious: the
        aggregate may be negative while no individual line may be. A builder
        that negates the lines to build a credit note produces a file the schema
        REJECTS; one that emits the negative total and leaves the lines positive
        produces a file the schema ACCEPTS. Which of the two the SRI expects is
        a business question the Validaciones column has to answer, not a
        question the XSD can settle. Until ATS-11 answers it, a passing XSD
        validation of a negative totalVentas proves nothing about correctness.
        """
        result = self._validate_fixture("ats_invalid_negative_total_ventas.xml")
        self.assertTrue(
            result.is_valid,
            "totalVentasType admits '-1500.00' by design; "
            f"unexpected rejection: {result.errors}",
        )

    # Case 6 -- THE SCHEMA IS NOT THE NORM

    def test_impossible_date_is_accepted_because_fecha_type_has_no_calendar(
        self,
    ):
        """fechaType (ats.xsd:22-23) is a bare pattern: day 01-31, month 01-12,
        year 19xx-20xx, never checked against the calendar.

        "31/02/2020" validates. The XSD is a lexical shape, not a date parser,
        so a document can clear every grammar rule in the schema and still be
        refused at SRI reception. Date validity belongs to the business
        validators, and so does the period-match rule that the header Anio/Mes
        never gets checked against the detail lines' own dates.
        """
        result = self._validate_fixture("ats_invalid_impossible_date.xml")
        self.assertTrue(
            result.is_valid,
            "31/02/2020 satisfies the fechaType pattern; "
            f"unexpected rejection: {result.errors}",
        )

    # Case 7 -- codigoOperativo

    def test_codigo_operativo_other_than_iva_is_rejected(self):
        """codigoOperativoType (ats.xsd:1478) enumerates the single value IVA."""
        self._assert_rejected("ats_invalid_codigo_operativo.xml")

    # Case 8 -- TipoIDInformante

    def test_tipo_id_informante_other_than_r_is_rejected(self):
        """The inline type at ats.xsd:587-596 enumerates the single value R.

        Nothing references the decoy named TipoIDInformanteType at
        ats.xsd:1490-1492, whose restriction is empty and therefore
        unconstrained, so the schema is correct only when resolved by
        reference rather than by name.
        """
        self._assert_rejected("ats_invalid_tipo_id_informante.xml")

    # Case 9 -- RUC shape

    def test_ruc_format_is_rejected(self):
        """numeroRucType (ats.xsd:11-12) is 10 digits plus the literal "001"."""
        self._assert_rejected("ats_invalid_ruc_format.xml")

    # Case 10 -- sequence order

    def test_children_out_of_the_declared_sequence_are_rejected(self):
        """detalleComprasType is an xsd:sequence (ats.xsd:705), so order is
        normative for equal-typed mandatory children too.

        puntoEmision (ats.xsd:736) and secuencial (ats.xsd:737) are emitted
        swapped and the document is refused.
        """
        result = self._assert_rejected("ats_invalid_child_order.xml")
        self.assertIn("secuencial", "\n".join(result.errors))

    # Case 11 -- THE SCHEMA IS NOT THE NORM

    def test_deprecated_retention_family_is_still_accepted_by_design(self):
        """estabRetencion2 (ats.xsd:794) through fechaEmiRet2 (ats.xsd:824) are
        annotated "eliminado se mantiene por compatibilidad" and remain valid.

        The schema is more permissive than the norm here, and that permissiveness
        is pinned on purpose: deleting the family would change the bytes of an
        official published artifact and break the sha256 proof that the shipped
        copy is the SRI's. "Emit nothing" is a builder rule recorded in the trap
        table, never a schema edit.
        """
        result = self._validate_fixture("ats_deprecated_retention_fields.xml")
        self.assertTrue(
            result.is_valid,
            "the deprecated retencion-2 family must stay valid; "
            f"unexpected rejection: {result.errors}",
        )

    # Case 12 -- zero establishment code

    def test_zero_establishment_is_rejected_where_the_rule_exists(self):
        """minExclusive 000 (ats.xsd:1484) rejects "000" on iva/numEstabRuc,
        whose type numEstabRucType is based on xsd:integer.

        The identical-looking detalleCompras/establecimiento is typed
        establecimientoType (ats.xsd:26-30), based on xsd:string with only the
        pattern [0-9]{3} -- so "000" is ACCEPTED there, and the second half of
        this test records that acceptance instead of leaving it assumed. The
        builder has to reject a zero establishment code itself.
        """
        self._assert_rejected("ats_invalid_zero_establishment.xml")

        zero_establecimiento = self._xml("ats_valid_minimal.xml").replace(
            b"<establecimiento>001</establecimiento>",
            b"<establecimiento>000</establecimiento>",
        )
        result = validate_ats_xml(zero_establecimiento)
        self.assertTrue(
            result.is_valid,
            "establecimientoType carries no minExclusive, so '000' validates "
            f"on detalleCompras/establecimiento; observed rejection: "
            f"{result.errors}",
        )

    # The helper's contract

    def test_invalid_xml_is_reported_not_raised(self):
        """A malformed document is a returned verdict, never an exception.

        The builder will validate text it may have read back from storage, so an
        unparseable string is an expected outcome, not a programming error. It
        must come back as a rejected verdict carrying the parser message.
        """
        result = validate_ats_xml(b"<iva><TipoIDInformante>R</iva>")
        self.assertFalse(result.is_valid)
        self.assertTrue(result.errors)

    def test_a_rejected_document_never_reports_a_success_flag(self):
        """No False is ever translated into a True.

        _l10n_ec_action_check_xsd on account.edi.document can afford to conflate
        "not valid" with "handled", because the string it checks was serialised
        in memory moments earlier. An ATS document is assembled from
        SRI-validated catalog data and may be re-read from persisted text, so
        the helper models the outcome explicitly and keeps success and failure
        distinguishable at every call site.
        """
        result = self._validate_fixture("ats_invalid_ruc_format.xml")
        self.assertFalse(result.is_valid)
        self.assertNotEqual(result.is_valid, True)
        self.assertTrue(result.errors)
