"""What the ATS builder must guarantee, and what it must refuse.

``l10n_ec_ats.builder`` is the seam between the collectors and the file. The
collectors hand back plain dicts keyed by ATS XML element names; the builder
turns them into one document. That makes it the only place where four
independent failures become visible at once, and each of the seven traps in the
plan's §5.4 table is one of them:

* a dict is unordered and ``detalleComprasType`` is an ``xsd:sequence``, so a
  builder that iterates the payload emits a file the SRI's schema refuses;
* a collector amount is a ``float``, and ``"100.5"`` is not a ``monedaType``;
* a partner name holds ``ñ`` and dots, and ``razonSocialType`` holds neither;
* ``establecimiento`` is the ninth child of a compras row and the second of an
  anulados row, so no single element order can serve both;
* ``ventasEstab`` is a ``totalVentasType`` and every other amount in the
  document is a ``monedaType``, so the *only* element that may carry a minus is
  the one a flattened field/type map would fold into the others.

So every test here ends at :func:`validate_ats_xml`. A builder test that never
validates proves only that the builder agrees with itself.

The other half of the contract is refusal. The collector never substitutes a
value it could not source and never invents an element, which means the builder
must not launder what it is handed: a negative line amount, a five-digit amount,
a two-character name and a deprecated element are all **refused**, with the
element named. Turning any of them into a filing would be the substitution this
addon exists to prevent, one layer up.

The specs the builder declares are not trusted by these tests either. Every
element name, in every order, with its type, and every lexical limit, is derived
from the shipped ``ats.xsd`` at test time and compared -- so "the builder matches
the schema" is an assertion rather than a claim.
"""

import re
from decimal import Decimal

from lxml import etree

from odoo.tests.common import TransactionCase
from odoo.tools import file_open

from ..builder import (
    ATS_AMOUNT,
    ATS_ANULADOS_SPEC,
    ATS_COMPRAS_SPEC,
    ATS_HEADER_SPEC,
    ATS_VENTAS_ESTABLECIMIENTO_SPEC,
    ATS_VENTAS_SPEC,
    ATS_XML_DECLARATION,
    ATS_XML_TRAILER,
    AtsBuilderError,
    build_ats_xml,
)
from ..schema import ATS_XSD_PATH, validate_ats_xml

FIXTURES_PATH = "l10n_ec_ats/tests/fixtures"

#: ``{http://www.w3.org/2001/XMLSchema}`` -- the XSD is read directly by the
#: schema-derivation tests below, which is the whole point of them.
XSD = "{http://www.w3.org/2001/XMLSchema}"


def _load_xsd():
    with file_open(ATS_XSD_PATH, "rb") as xsd_file:
        return etree.parse(xsd_file).getroot()


def xsd_particles(type_name, types=None):
    """The ``(name, type, minOccurs)`` children of ``type_name``, in document order.

    ``xsd:extension`` appends its own particles to the base type's, so the base
    has to be walked first or the extension's members come out first and the order
    is wrong. ``detalleAirComprasType`` is the case that proves it: it extends
    ``detalleAirType``, so its real content model is ``codRetAir, baseImpAir,
    porcentajeAir, valRetAir`` **then** the five dividend-payment elements -- not
    the five alone, which is what a reader that looks only at the type's own
    children concludes.

    ``minOccurs`` comes along because it is the third axis the builder has to get
    right per block: it is what separates "this element is mandatory here" from
    "this element is mandatory in the other block", which is how the spec decides
    between refusing an absent key and emitting no element.
    """
    if types is None:
        types = {
            node.get("name"): node for node in _load_xsd().iter(f"{XSD}complexType")
        }
    node = types[type_name]
    content = node.find(f"{XSD}complexContent")
    if content is not None:
        extension = content.find(f"{XSD}extension")
        if extension is not None:
            base = extension.get("base")
            inherited = xsd_particles(base, types) if base in types else []
            return inherited + _own_particles(extension)
    return _own_particles(node)


def _own_particles(node):
    """The ``(name, type, minOccurs)`` triples declared directly on ``node``."""
    return [
        (
            element.get("name"),
            element.get("type"),
            element.get("minOccurs", "1"),
        )
        for element in node.iter(f"{XSD}element")
    ]


def xsd_simple_type(type_name):
    """``type_name``'s base, pattern and inclusive bounds."""
    restriction = _load_xsd().find(
        f"{XSD}simpleType[@name='{type_name}']/{XSD}restriction"
    )
    pattern = restriction.find(f"{XSD}pattern")
    minimum = restriction.find(f"{XSD}minInclusive")
    maximum = restriction.find(f"{XSD}maxInclusive")
    return {
        "base": restriction.get("base"),
        "pattern": pattern.get("value") if pattern is not None else "",
        "min": minimum.get("value") if minimum is not None else "",
        "max": maximum.get("value") if maximum is not None else "",
    }


def _emitted(spec, row):
    """The element names a row should emit: the declared order, minus what is absent.

    An optional element the payload did not carry produces **no element**, so it is
    a gap in the sequence rather than an empty entry in it. Comparing an emitted
    document against the whole declared order would therefore fail on a perfectly
    correct row; comparing against ``spec`` filtered by what the payload carried is
    the assertion that actually describes the contract.
    """
    carried = {
        name for name, value in row.items() if value is not None and value is not False
    }
    return [field.name for field in spec if field.emitted and field.name in carried]


class TestAtsBuilder(TransactionCase):
    """The builder's contract: schema-valid output, refusal instead of repair."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _golden(self, fixture_name):
        """The expected document, minus its documentation comment.

        The comment is worth keeping -- it records which sequence and which types
        the golden depends on, the way every other fixture in this directory does
        -- but the builder emits no comment, so comparing the file as it sits on
        disk would be a comparison of prose against XML. Only the leading
        ``<!-- ... -->`` block is removed; the declaration, the indentation and
        every element are compared byte for byte.
        """
        with file_open(f"{FIXTURES_PATH}/{fixture_name}", "rb") as golden_file:
            text = golden_file.read().decode("utf-8")
        return re.sub(r"<!--.*?-->\n", "", text, count=1, flags=re.DOTALL)

    def _assert_valid(self, payload, message=""):
        """Build, validate, and return the document.

        Every single assertion in this file goes through here. That is the reason
        the class needs a database at all: ``build_ats_xml`` is pure and touches
        no record, but ``validate_ats_xml`` reads the shipped XSD through
        ``file_open``, which resolves inside the addons path.
        """
        document = build_ats_xml(payload)
        result = validate_ats_xml(document)
        self.assertTrue(
            result.is_valid,
            f"{message} builder produced an invalid document: {result.errors}",
        )
        return document

    def _assert_refused(self, payload, expected_fragment):
        with self.assertRaises(AtsBuilderError) as caught:
            build_ats_xml(payload)
        self.assertIn(
            expected_fragment,
            str(caught.exception),
            "a refusal has to name what it refused, or nobody can fix it",
        )
        return str(caught.exception)

    def _compras_row(self, **overrides):
        """One ``detalleCompras`` payload, in ATS-06's shape.

        Keyed by ATS element name and carrying ``float`` amounts, which is
        exactly what the collector returns.
        """
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

    def _ventas_row(self, **overrides):
        row = {
            "tpIdCliente": "01",
            "idCliente": "1791311225001",
            "tipoComprobante": "18",
            "tipoEmision": "E",
            "numeroComprobantes": 1,
            "baseNoGraIva": 0.0,
            "baseImponible": 0.0,
            "baseImpGrav": 100.0,
            "montoIva": 12.0,
            "montoIce": 0.0,
            "valorRetIva": 0.0,
            "valorRetRenta": 0.0,
        }
        row.update(overrides)
        return row

    def _anulado_row(self, **overrides):
        row = {
            "tipoComprobante": "01",
            "establecimiento": "001",
            "puntoEmision": "001",
            "secuencialInicio": "000000005",
            "secuencialFin": "000000005",
            "autorizacion": "123456789012",
        }
        row.update(overrides)
        return row

    def _header(self, **overrides):
        header = {
            "TipoIDInformante": "R",
            "IdInformante": "1791311225001",
            "razonSocial": "COMERCIAL ANDINA SA",
            "Anio": 2024,
            "Mes": "03",
            "regimenMicroempresa": False,
            "numEstabRuc": "001",
            "totalVentas": 100.0,
            "codigoOperativo": "IVA",
        }
        header.update(overrides)
        return header

    def _payload(self, **blocks):
        payload = {
            "header": self._header(),
            "compras": [],
            "ventas": [],
            "ventasEstablecimiento": [],
            "anulados": [],
        }
        payload.update(blocks)
        return payload

    def _text_of(self, document, path):
        return etree.fromstring(document.encode("utf-8")).findtext(path)

    def _children_of(self, document, path):
        """The child element names at ``path``, in emitted order.

        ``path`` is relative to the root, and ``""`` means the root itself --
        which is what the header assertions need, since ``find("iva")`` would look
        for a *child* of the root and find nothing.

        This is how the order assertions are made exact rather than approximate:
        not "is ``secuencial`` before ``establecimiento``" but the whole list,
        compared against the declared sequence.
        """
        root = etree.fromstring(document.encode("utf-8"))
        node = root if not path else root.find(path)
        if node is None:
            return None
        return [child.tag for child in node]

    # ------------------------------------------------------------------
    # The four blocks each build a schema-valid document
    # ------------------------------------------------------------------

    def test_compras_block_builds_a_schema_valid_document(self):
        """One purchases row, with the nested ``air`` and ``formasDePago`` blocks.

        ``air`` and ``formasDePago`` are the two elements of ``detalleComprasType``
        that are not scalars: each wraps an unbounded list of dicts with its own
        content model. They are in the same row on purpose -- a builder that
        handles the flat elements and mishandles the nested ones still passes a
        shallow test.
        """
        document = self._assert_valid(
            self._payload(
                compras=[
                    self._compras_row(
                        baseImponible=0.0,
                        baseImpGrav=120.0,
                        montoIva=18.0,
                        air=[
                            {
                                "codRetAir": "312C",
                                "baseImpAir": 120.0,
                                "porcentajeAir": 1.75,
                                "valRetAir": 2.10,
                            }
                        ],
                        formasDePago=[{"formaPago": "01"}],
                    )
                ]
            ),
            "compras with air and formasDePago",
        )
        self.assertIn("<codRetAir>312C</codRetAir>", document)
        self.assertIn("<porcentajeAir>1.75</porcentajeAir>", document)
        self.assertIn("<formaPago>01</formaPago>", document)
        self.assertEqual(
            self._children_of(document, "compras/detalleCompras/air/detalleAir"),
            ["codRetAir", "baseImpAir", "porcentajeAir", "valRetAir"],
        )

    def test_ventas_block_builds_a_schema_valid_document(self):
        document = self._assert_valid(
            self._payload(
                ventas=[
                    self._ventas_row(
                        parteRelVtas="NO", formasDePago=[{"formaPago": "01"}]
                    )
                ]
            ),
            "ventas",
        )
        self.assertEqual(self._text_of(document, "totalVentas"), "100.00")
        row = self._ventas_row(parteRelVtas="NO", formasDePago=[{"formaPago": "01"}])
        self.assertEqual(
            self._children_of(document, "ventas/detalleVentas"),
            _emitted(ATS_VENTAS_SPEC, row),
            "an absent optional element is a gap in the order, never an empty one, "
            "so the emitted sequence is the declared one filtered to the keys the "
            "payload actually carried",
        )

    def test_ventas_establecimiento_block_builds_a_schema_valid_document(self):
        document = self._assert_valid(
            self._payload(
                ventasEstablecimiento=[
                    {"codEstab": "001", "ventasEstab": 100.0},
                    {"codEstab": "002", "ventasEstab": 40.0},
                ]
            ),
            "ventasEstablecimiento",
        )
        self.assertEqual(
            self._children_of(document, "ventasEstablecimiento"),
            ["ventaEst", "ventaEst"],
        )
        self.assertEqual(
            self._text_of(document, "ventasEstablecimiento/ventaEst/codEstab"), "001"
        )

    def test_anulados_block_builds_a_schema_valid_document(self):
        document = self._assert_valid(
            self._payload(anulados=[self._anulado_row(secuencialFin="000000007")]),
            "anulados",
        )
        self.assertEqual(
            self._text_of(document, "anulados/detalleAnulados/secuencialFin"),
            "000000007",
        )

    # ------------------------------------------------------------------
    # Golden document -- exact bytes, so order is asserted and not assumed
    # ------------------------------------------------------------------

    def test_every_block_together_matches_the_golden_document_byte_for_byte(self):
        """The whole document, all four blocks, compared as text.

        Byte equality is the only assertion that pins *order* rather than
        membership: a builder that emitted the right elements in the wrong order
        still validates against a ``set`` comparison, and still fails this one.
        """
        document = self._assert_valid(
            self._payload(
                compras=[self._compras_row()],
                ventas=[self._ventas_row()],
                ventasEstablecimiento=[{"codEstab": "001", "ventasEstab": 100.0}],
                anulados=[self._anulado_row()],
            ),
            "the four-block document",
        )
        self.assertEqual(document, self._golden("ats_builder_all_blocks.xml"))

    def test_the_builder_does_not_reorder_the_payload_it_is_given(self):
        """Insertion order of the dict is irrelevant; the declared order wins.

        The payload below is built with the elements in reverse schema order --
        ``autorizacion`` first, ``codSustento`` last -- which is what a collector
        assembling a row by appending as it goes can easily produce, and what a
        plain ``for key in row`` builder would emit verbatim.
        """
        row = self._compras_row()
        shuffled = dict(reversed(list(row.items())))
        document = self._assert_valid(
            self._payload(compras=[shuffled]), "a compras row in reverse order"
        )
        self.assertEqual(
            self._children_of(document, "compras/detalleCompras"),
            _emitted(ATS_COMPRAS_SPEC, row),
            "the declared order, not the payload's insertion order",
        )

    # ------------------------------------------------------------------
    # TRAP 1 -- the decimal pattern
    # ------------------------------------------------------------------

    def test_trap_01_every_amount_emits_exactly_two_decimals(self):
        """``[0-9]{1,12}\\.[0-9]{2}|[0-9]{1,12}`` admits two decimals or none.

        ``100.5`` matches neither alternative, which is the case ATS-04 pinned as
        ``test_amount_with_a_single_decimal_is_rejected``. A collector amount is a
        Python ``float`` and ``str(100.5)`` is ``"100.5"``, so a builder that
        interpolates it produces a document the schema refuses. The builder
        quantises to two decimals instead, always -- ``100.50``, never ``100.5``
        and never ``100.50000000000001``.
        """
        document = self._assert_valid(
            self._payload(compras=[self._compras_row(baseImponible=100.5)]),
            "an amount that needs rounding",
        )
        self.assertIn("<baseImponible>100.50</baseImponible>", document)

    def test_trap_01_rounding_is_half_up_not_banker_rounding(self):
        """ROUND_HALF_UP, because that is what Odoo and the SRI both use.

        The distinction is visible at exactly one decimal place. ``Decimal(str(x))``
        keeps the digits the collector actually meant and quantises them; a binary
        float cannot, because ``2.665`` is not representable and the nearest
        double is below it. Half-up on the decimal digits gives ``2.67``;
        banker's rounding and C's default would both give ``2.66``. Asserting
        ``2.665`` rather than ``2.675`` is what makes this test discriminate.
        """
        document = self._assert_valid(
            self._payload(compras=[self._compras_row(baseImponible=2.665)]),
            "a half-cent amount",
        )
        self.assertIn("<baseImponible>2.67</baseImponible>", document)

    def test_amounts_at_the_twelve_digit_boundary(self):
        """The pattern allows twelve integer digits, and exactly twelve.

        ``999999999999.99`` is the ``xsd:maxInclusive`` and must be emitted
        unchanged. One more cent exceeds it, and one more integer digit exceeds
        the pattern too -- which is why the bound is checked as a magnitude and
        not as a string length.
        """
        at_bound = self._assert_valid(
            self._payload(compras=[self._compras_row(baseImponible=999999999999.99)]),
            "the largest amount monedaType admits",
        )
        self.assertIn("<baseImponible>999999999999.99</baseImponible>", at_bound)

        # A Decimal carries exactly what the caller meant, with no float in the
        # way, so the boundary is reachable without a rounding artefact.
        as_decimal = self._assert_valid(
            self._payload(compras=[self._compras_row(baseImpGrav=Decimal("1.005"))]),
            "a Decimal amount needing a third decimal place",
        )
        self.assertIn("<baseImpGrav>1.01</baseImpGrav>", as_decimal)

        self._assert_refused(
            self._payload(compras=[self._compras_row(baseImponible=1000000000000.0)]),
            "baseImponible",
        )
        self._assert_refused(
            self._payload(compras=[self._compras_row(baseImponible=999999999999.999)]),
            "baseImponible",
        )

    def test_an_over_long_amount_is_refused_and_never_truncated(self):
        """Refusal, not truncation.

        Silently clamping to twelve digits would file a number the company never
        had, and silently dropping digits would file a different number; both are
        the substitution the collectors refuse to perform one layer down.
        """
        self._assert_refused(
            self._payload(compras=[self._compras_row(baseImpGrav=1234567890123.45)]),
            "baseImpGrav",
        )

    # ------------------------------------------------------------------
    # TRAP 2 -- the text whitelist
    # ------------------------------------------------------------------

    def test_trap_02_razon_social_is_reduced_to_the_schema_whitelist(self):
        """``razonSocialType`` is ``[a-zA-Z0-9\\s]``, and that is the whole rule.

        It is stricter than "strip the accents": every character outside the class
        has to go, including the dot of ``S.A.`` -- which ATS-04 pinned as
        ``test_accented_razon_social_is_rejected`` and proved with a document whose
        only defect was the dot. A real Ecuadorian company name therefore loses the
        accents **and** its punctuation.
        """
        document = self._assert_valid(
            self._payload(
                header=self._header(razonSocial="COMPAÑIA ÑANDINA S.A."),
                compras=[self._compras_row()],
            ),
            "an accented, punctuated company name",
        )
        self.assertEqual(self._text_of(document, "razonSocial"), "COMPANIA NANDINA SA")

    def test_trap_02_accents_are_folded_including_ene_tilde(self):
        """Every accent in the Spanish alphabet folds to its plain letter.

        ``ñ`` is the one that is not an accent in the combining-mark sense: NFKD
        decomposes it to ``n`` plus U+0303, so dropping the combining mark leaves
        ``n``, and ``Ñ`` behaves identically. Asserting all twelve keeps a future
        normalisation change from quietly restoring one of them.
        """
        document = self._assert_valid(
            self._payload(
                header=self._header(razonSocial="ÁÉÍÓÚÑáéíóúñ ANDINA SA"),
                compras=[self._compras_row()],
            ),
            "the whole accented alphabet",
        )
        self.assertEqual(
            self._text_of(document, "razonSocial"), "AEIOUNaeioun ANDINA SA"
        )

    def test_punctuation_vanishes_rather_than_becoming_a_space(self):
        """Dropped, not replaced -- and the reason is that dropping is weaker.

        Replacing each discarded character with a space would *invent* a word
        boundary the record never contained, and would miss the case that matters:
        ``S.R.L.`` is written ``SRL`` in the Ecuadorian company register, while
        ``S R L`` is written nowhere. Dropping is also the conservative direction:
        it can only remove what the schema cannot carry, so no character in the
        file is absent from the record. The test pins the merge as well as the
        drop, because merging is the visible cost and must not be a surprise.

        This is the same rule ATS-06 applies to ``denoProv`` and ``denoCli``, so a
        builder that spelled it differently would give one document three different
        spellings of one rule.
        """
        document = self._assert_valid(
            self._payload(
                header=self._header(razonSocial="ACME S.R.L. CIA LTDA"),
                compras=[self._compras_row()],
            ),
            "a punctuated legal-form suffix",
        )
        self.assertEqual(self._text_of(document, "razonSocial"), "ACME SRL CIA LTDA")

    def test_razon_social_minimum_length_is_measured_after_stripping(self):
        """After, not before -- and the length floor is a business rule anyway.

        The ficha's five-character minimum is in the ``Validaciones`` column, not
        in ``ats.xsd``: ``razonSocialType``'s own pattern would accept ``ABC``. So
        ATS-11 owns the rule; the builder refuses a name that fails it rather than
        filing one the SRI rejects, which is the same refusal §5.4b asks of it for a
        ``000`` establishment.

        Measured **after** stripping, for two reasons. The constraint exists
        because the SRI's systems must display a name, so it constrains the string
        that gets filed, and that is the stripped string. And measured before it is
        trivially bypassable: ``SA----`` is six characters going in and ``SA``
        coming out, so the rule would admit exactly the names it exists to exclude.
        """
        document = self._assert_valid(
            self._payload(
                header=self._header(razonSocial="ANDE SA"),
                compras=[self._compras_row()],
            ),
            "a five-character name",
        )
        self.assertEqual(self._text_of(document, "razonSocial"), "ANDE SA")

        # Four characters of real content fail, and the refusal names the field.
        self._assert_refused(
            self._payload(
                header=self._header(razonSocial="ANDE"), compras=[self._compras_row()]
            ),
            "razonSocial",
        )
        # Six characters in, two out: the bypass above is closed.
        self._assert_refused(
            self._payload(
                header=self._header(razonSocial="SA----"), compras=[self._compras_row()]
            ),
            "razonSocial",
        )

    def test_surrounding_and_repeated_whitespace_is_collapsed(self):
        """``razonSocialType`` declares **no** ``whiteSpace`` facet.

        XSD then applies ``preserve``, so a leading space reaches the pattern
        ``[a-zA-Z0-9][a-zA-Z0-9\\s]+[a-zA-Z0-9\\s]``, whose first character class
        has no whitespace in it, and the document is refused. The builder therefore
        collapses and trims itself rather than relying on a facet that is not there.
        Tabs and newlines fold to a single space for the same reason: XSD's ``\\s`` is
        only space, tab, CR and LF.
        """
        document = self._assert_valid(
            self._payload(
                header=self._header(razonSocial="  COMERCIAL\t\tANDINA\nSA  "),
                compras=[self._compras_row()],
            ),
            "a name with stray whitespace",
        )
        self.assertEqual(self._text_of(document, "razonSocial"), "COMERCIAL ANDINA SA")

    def test_deno_prov_and_deno_cli_survive_the_same_reduction(self):
        """``denoProvType`` and ``denoCli`` are the same whitelist as
        ``razonSocialType``, on both the purchase and the sale side.

        ``denoProvType``'s pattern is ``[a-zA-Z0-9][a-zA-Z0-9\\s]*`` -- no length
        floor -- which is a genuine difference from ``razonSocialType`` and the
        reason the floor is declared per field rather than once for "a name".
        """
        document = self._assert_valid(
            self._payload(
                compras=[
                    self._compras_row(
                        tpIdProv="03",
                        tipoProv="02",
                        denoProv="EXPORTADORA ÑANDINA S.A.",
                    )
                ]
            ),
            "a foreign supplier with an accented name",
        )
        self.assertEqual(
            self._text_of(document, "compras/detalleCompras/denoProv"),
            "EXPORTADORA NANDINA SA",
        )

    # ------------------------------------------------------------------
    # TRAP 3 -- no negatives per line
    # ------------------------------------------------------------------

    def test_trap_03_line_amounts_cannot_carry_a_negative(self):
        """``monedaType`` sets ``minInclusive 0.0`` and its pattern has no minus.

        A credit note cannot be expressed by negating a line amount: ATS-04 pinned
        that as ``test_negative_line_amount_is_rejected``. The builder therefore
        **refuses** a negative rather than taking its absolute value. Absolute-ing
        would be a substitution -- it would file a magnitude for a value the caller
        handed over, and it would hide a collector that regressed. ATS-06 already
        emits ``abs()`` amounts; a negative arriving here means the contract was
        broken somewhere and generation has to stop.
        """
        self._assert_refused(
            self._payload(compras=[self._compras_row(montoIva=-15.0)]), "montoIva"
        )

    def test_trap_03_the_same_base_is_refused_on_both_blocks(self):
        """``baseImponible`` is a ``monedaType`` in ``compras`` and in ``ventas``.

        Two blocks, two independent rows, two refusals. If only the purchases side
        were guarded, an aggregated sales row would be the way to smuggle a
        negative into a file.
        """
        self._assert_refused(
            self._payload(compras=[self._compras_row(baseImponible=-100.0)]),
            "baseImponible",
        )
        self._assert_refused(
            self._payload(ventas=[self._ventas_row(baseImpGrav=-100.0)]), "baseImpGrav"
        )
        self._assert_refused(
            self._payload(ventas=[self._ventas_row(valorRetRenta=-1.0)]),
            "valorRetRenta",
        )

    def test_ventas_estab_is_the_only_amount_that_may_carry_a_negative(self):
        """``ventasEstab`` is a ``totalVentasType``; every other amount is not.

        This is the credit-note sign decision, and it is one mechanism rather than
        two: ``totalVentasType`` is the only amount type in the whole schema whose
        pattern admits a leading minus, and inside the Tipo 1 scope it carries
        exactly two elements -- ``iva/totalVentas`` and ``ventaEst/ventasEstab``. So
        "which element may hold a sign" is answered by the element's own type, which
        is a per-block fact, and a flattened "an amount is an amount" map cannot
        answer it.

        A negative net is real: a company that credited more than it invoiced from
        one establishment has a negative net figure, and clamping it to ``0.00``
        would state a number the company never had.
        """
        document = self._assert_valid(
            self._payload(
                ventasEstablecimiento=[{"codEstab": "001", "ventasEstab": -50.0}],
                header=self._header(totalVentas=-50.0),
            ),
            "a negative net and a negative gross",
        )
        self.assertIn("<ventasEstab>-50.00</ventasEstab>", document)
        self.assertIn("<totalVentas>-50.00</totalVentas>", document)

    def test_a_credit_note_is_filed_as_its_own_row_with_positive_amounts(self):
        """The sign lives on the establishment net, never on the ``ventas`` rows.

        A period with a 100.00 invoice and a 40.00 credit note files **two**
        ``detalleVentas`` rows -- one under the invoice's document type, one under
        the credit note's -- both with positive magnitudes. The credit note is
        identified by its ``tipoComprobante``, not by a sign. The two rows then sum
        to a ``totalVentas`` of 140.00 (gross, per ``ESQUEMA`` row 10) while the
        establishment's net is 60.00, which is what makes the ficha's *"la sumatoria
        del total de ventas por los establecimientos no puede ser mayor al valor
        registrado en el campo total ventas"* a real constraint rather than an
        equality.

        The rejected alternative was negating the ``ventas`` rows -- impossible,
        since ``monedaType`` forbids it -- or negating ``totalVentas``, which
        satisfies the schema but breaks the ficha's definition of the field.
        """
        document = self._assert_valid(
            self._payload(
                ventas=[
                    self._ventas_row(
                        tipoComprobante="18",
                        baseImpGrav=100.0,
                        montoIva=12.0,
                        numeroComprobantes=1,
                    ),
                    self._ventas_row(
                        tipoComprobante="04",
                        baseImpGrav=40.0,
                        montoIva=4.8,
                        numeroComprobantes=1,
                    ),
                ],
                ventasEstablecimiento=[{"codEstab": "001", "ventasEstab": 60.0}],
                header=self._header(totalVentas=140.0),
            ),
            "an invoice and its credit note",
        )
        self.assertIn("<tipoComprobante>18</tipoComprobante>", document)
        self.assertIn("<tipoComprobante>04</tipoComprobante>", document)
        self.assertIn("<baseImpGrav>100.00</baseImpGrav>", document)
        self.assertIn("<baseImpGrav>40.00</baseImpGrav>", document)
        self.assertNotIn("<baseImpGrav>-", document)
        self.assertIn("<ventasEstab>60.00</ventasEstab>", document)
        self.assertIn("<totalVentas>140.00</totalVentas>", document)

    # ------------------------------------------------------------------
    # TRAP 4 -- element order is normative
    # ------------------------------------------------------------------

    def test_trap_04_compras_elements_follow_the_declared_sequence(self):
        """``detalleComprasType`` is an ``xsd:sequence``: order, not membership.

        ATS-04 pinned the rejection with ``puntoEmision`` and ``secuencial`` swapped,
        and the interleaved ``Tabla 11`` run is the harder case: the six retention
        elements are adjacent but not interchangeable (``valRetBien10``,
        ``valRetServ20``, ``valorRetBienes``, ``valRetServ50``,
        ``valorRetServicios``, ``valRetServ100``), so emitting them sorted, or in the
        order the collector happened to bucket them, is wrong.
        """
        document = self._assert_valid(
            self._payload(
                compras=[
                    self._compras_row(
                        valRetBien10=1.0,
                        valRetServ20=2.0,
                        valorRetBienes=3.0,
                        valRetServ50=4.0,
                        valorRetServicios=5.0,
                        valRetServ100=6.0,
                    )
                ]
            ),
            "every retention element populated",
        )
        self.assertEqual(
            self._children_of(document, "compras/detalleCompras"),
            _emitted(
                ATS_COMPRAS_SPEC,
                self._compras_row(
                    valRetBien10=1.0,
                    valRetServ20=2.0,
                    valorRetBienes=3.0,
                    valRetServ50=4.0,
                    valorRetServicios=5.0,
                    valRetServ100=6.0,
                ),
            ),
        )
        for element, value in (
            ("valRetBien10", "1.00"),
            ("valRetServ20", "2.00"),
            ("valorRetBienes", "3.00"),
            ("valRetServ50", "4.00"),
            ("valorRetServicios", "5.00"),
            ("valRetServ100", "6.00"),
        ):
            self.assertIn(f"<{element}>{value}</{element}>", document)

    def test_trap_04_the_header_sequence_is_also_normative(self):
        """``regimenMicroempresa``, ``numEstabRuc`` and ``totalVentas`` sit
        **between** ``Mes`` and ``codigoOperativo``.

        This is the trap's sharpest form: the three optional header fields are
        declared before the mandatory ``codigoOperativo``, so appending them after
        it -- which any builder that treats "required" as "first" does -- is a
        sequence violation.
        """
        document = self._assert_valid(
            self._payload(
                header=self._header(regimenMicroempresa="SI"),
                ventasEstablecimiento=[{"codEstab": "001", "ventasEstab": 100.0}],
            ),
            "a header carrying regimenMicroempresa",
        )
        self.assertEqual(
            # The first nine children are the scalars; the rest are the block
            # wrappers, whose own ordering has its own tests. What matters here is
            # that regimenMicroempresa, numEstabRuc and totalVentas land *before*
            # codigoOperativo rather than after it.
            self._children_of(document, "")[:9],
            [
                "TipoIDInformante",
                "IdInformante",
                "razonSocial",
                "Anio",
                "Mes",
                "regimenMicroempresa",
                "numEstabRuc",
                "totalVentas",
                "codigoOperativo",
            ],
        )
        self.assertIn("<regimenMicroempresa>SI</regimenMicroempresa>", document)

    def test_an_element_the_schema_does_not_declare_is_refused_not_dropped(self):
        """An unknown key is a broken contract, so it stops generation.

        The alternative -- ignoring a key the builder does not recognise -- is how a
        field goes missing from a filed ATS while every test still passes. The
        collector will be the thing that starts emitting it, and this refusal is
        what makes that visible on the day it happens.
        """
        self._assert_refused(
            self._payload(compras=[self._compras_row(baseImponibleFoo=1.0)]),
            "baseImponibleFoo",
        )

    def test_a_mandatory_element_the_collector_omitted_is_refused(self):
        """Absence is not a zero.

        ``montoIce`` is ``minOccurs="1"`` on a compras row, so a payload that omits
        it would produce a document the schema refuses anyway. Saying so with the
        element named is more useful than a libxml2 line number, and it keeps the
        builder from inventing a default it has no source for.
        """
        row = self._compras_row()
        del row["montoIce"]
        self._assert_refused(self._payload(compras=[row]), "montoIce")

    def test_an_optional_element_the_collector_omitted_produces_no_element(self):
        """``parteRel`` is optional, so its absence is normal.

        ATS-07 omits ``parteRelVtas`` for the final-consumer sentinel rather than
        emitting an empty one, and the same has to hold here: ``minOccurs="0"``
        means no element, never an empty element.
        """
        row = self._compras_row()
        del row["parteRel"]
        document = self._assert_valid(
            self._payload(compras=[row]), "a row without the optional parteRel"
        )
        self.assertNotIn("parteRel", document)

    # ------------------------------------------------------------------
    # TRAP 5 -- fechaType
    # ------------------------------------------------------------------

    def test_trap_05_dates_are_lexical_only_and_never_calendar_checked(self):
        """``fechaType`` is a bare pattern: ``dd/mm/yyyy``, years 19xx-20xx.

        No calendar check. ``31/02/2020`` satisfies it, which ATS-04 pinned as
        ``test_impossible_date_is_accepted_because_fecha_type_has_no_calendar``. So
        the builder **accepts** ``31/02/2020`` and emits it unchanged: adding a
        calendar check here would be the builder re-deriving a business rule the
        schema deliberately leaves open, and it would refuse a document the SRI's
        own validator accepts. Date validity belongs to ATS-11.

        The builder's half of the contract is the other one: the shape. A month of
        ``13`` or a day of ``41`` is not ``fechaType`` at all, and is refused.
        """
        document = self._assert_valid(
            self._payload(
                compras=[
                    self._compras_row(
                        fechaRegistro="31/02/2020", fechaEmision="31/02/2020"
                    )
                ]
            ),
            "an impossible but lexically valid date",
        )
        self.assertIn("<fechaRegistro>31/02/2020</fechaRegistro>", document)

        self._assert_refused(
            self._payload(compras=[self._compras_row(fechaRegistro="31/13/2020")]),
            "fechaRegistro",
        )
        self._assert_refused(
            self._payload(compras=[self._compras_row(fechaRegistro="41/01/2020")]),
            "fechaRegistro",
        )
        self._assert_refused(
            self._payload(compras=[self._compras_row(fechaRegistro="2020-02-31")]),
            "fechaRegistro",
        )
        self._assert_refused(
            self._payload(compras=[self._compras_row(fechaRegistro="29/02/1899")]),
            "fechaRegistro",
        )

    def test_trap_05_a_header_year_below_2000_is_refused(self):
        """``fechaType`` allows 19xx; the header's ``Anio`` does not.

        ``Anio`` is an ``anioType``, not a ``fechaType``: pattern ``\\d{4}`` with
        ``minInclusive 2000``. So a period of 1999 produces detail dates the schema
        accepts and a header year it refuses. That asymmetry is in the published
        artifact and is worth pinning, because a builder that reached for one date
        type for both would accept a file the SRI rejects and would not know which
        of the two was at fault.
        """
        self._assert_refused(self._payload(header=self._header(Anio=1999)), "Anio")
        self._assert_valid(
            self._payload(header=self._header(Anio=2000)),
            "the first year anioType admits",
        )

    # ------------------------------------------------------------------
    # TRAP 6 -- prefixed type aliases, never a flattened model
    # ------------------------------------------------------------------

    def test_trap_06_order_and_type_are_declared_per_block_and_never_flattened(self):
        """The builder's declared specs must equal the shipped schema's.

        Every element name, in every order, with its type, for all five blocks the
        builder owns -- derived from ``ats.xsd`` at test time and compared. That is
        what makes the alias trap mechanical instead of a matter of opinion: the
        specs are not a claim about the schema, they are checked against it.

        Three things follow, and each is asserted separately so a failure says
        which one broke:

        1. **Inheritance.** ``detalleAirComprasType`` extends ``detalleAirType``, so
           ``codRetAir``..``valRetAir`` precede the five dividend elements. A reader
           that ignores ``xsd:extension`` believes ``air`` carries none of them,
           which is why the resolver here walks the base first.
        2. **Order is per block.** ``establecimiento`` is the ninth child of a
           compras row and the second of an anulados row; ``tipoComprobante`` is
           fourth, first and sixth respectively. One order cannot serve all three.
        3. **Type is per block.** ``ventasEstab`` and ``totalVentas`` are
           ``totalVentasType``; every other amount in the document is
           ``monedaType``. That is the credit-note sign question, and it is
           answered by an element's own type.
        """
        types = {
            node.get("name"): node for node in _load_xsd().iter(f"{XSD}complexType")
        }
        for spec, type_name, label in (
            (ATS_COMPRAS_SPEC, "detalleComprasType", "compras"),
            (ATS_VENTAS_SPEC, "detalleVentasType", "ventas"),
            (
                ATS_VENTAS_ESTABLECIMIENTO_SPEC,
                "ventaEstType",
                "ventasEstablecimiento",
            ),
            (ATS_ANULADOS_SPEC, "detalleAnuladosType", "anulados"),
        ):
            self.assertEqual(
                [
                    (field.name, field.xsd_type, field.min_occurs)
                    for field in spec
                    if field.xsd_type
                ],
                xsd_particles(type_name, types),
                f"the {label} spec must reproduce {type_name} exactly -- every "
                f"element, in order, with its type and its cardinality",
            )

        self.assertEqual(
            [(field.name, field.xsd_type) for field in ATS_HEADER_SPEC],
            [
                # TipoIDInformante carries an inline type rather than a named one,
                # so the attribute is absent and reads back as None; the spec's ""
                # is the same fact.
                (name, type_name or "")
                for name, type_name, _min in xsd_particles("ivaType", types)
            ],
            "the header spec must reproduce ivaType's children, in order",
        )

        air_spec = next(field for field in ATS_COMPRAS_SPEC if field.name == "air")
        self.assertEqual(
            [
                (child.name, child.xsd_type, child.min_occurs)
                for child in air_spec.children
                if child.xsd_type
            ],
            xsd_particles("detalleAirComprasType", types),
            "the air spec must reproduce detalleAirComprasType including the "
            "inherited codRetAir..valRetAir prefix",
        )
        formas_spec = next(
            field for field in ATS_COMPRAS_SPEC if field.name == "formasDePago"
        )
        self.assertEqual(
            [
                (child.name, child.xsd_type, child.min_occurs)
                for child in formas_spec.children
                if child.xsd_type
            ],
            xsd_particles("formasDePagoType", types),
        )

    def test_trap_06_min_occurs_differs_per_block_for_the_same_element(self):
        """``montoIce`` is mandatory on compras and optional on ventas.

        The third axis of the alias trap, and the one a flattened model loses
        first: a single ``{name: required}`` map has to be wrong for at least one
        of the two blocks. The builder's specs carry ``min_occurs`` per element,
        and that is what decides whether an absent key is refused or simply
        produces no element.
        """
        compras = {field.name: field for field in ATS_COMPRAS_SPEC}
        ventas = {field.name: field for field in ATS_VENTAS_SPEC}
        self.assertEqual(compras["montoIce"].min_occurs, "1")
        self.assertEqual(ventas["montoIce"].min_occurs, "0")
        # And the behaviour differs with it: absent from ventas is fine, absent
        # from compras is refused.
        document = self._assert_valid(
            self._payload(ventas=[self._ventas_row(montoIce=0.0)]),
            "a ventas row that carries montoIce",
        )
        self.assertIn("<montoIce>0.00</montoIce>", document)
        row = self._ventas_row()
        del row["montoIce"]
        self._assert_valid(
            self._payload(ventas=[row]), "a ventas row without the optional montoIce"
        )
        compras_row = self._compras_row()
        del compras_row["montoIce"]
        self._assert_refused(self._payload(compras=[compras_row]), "montoIce")

    def test_trap_06_a_flattened_spec_cannot_represent_the_document(self):
        """Proof that merging the specs would be wrong, not merely tidy.

        A single ``{name: (position, type)}`` map is the shape a flattened model
        takes, and it is unsatisfiable for this schema. Both collisions are derived
        from the XSD rather than asserted, so this test keeps its meaning if the
        schema is ever refreshed:

        * ``establecimiento`` sits at three different indices in three blocks;
        * ``totalVentasType`` and ``monedaType`` are both amounts, and which
          elements get the signed one is what decides where a credit note's sign
          may go.
        """
        types = {
            node.get("name"): node for node in _load_xsd().iter(f"{XSD}complexType")
        }
        positions = {}
        typed = {}
        for block, type_name in (
            ("iva", "ivaType"),
            ("ventaEst", "ventaEstType"),
            ("compras", "detalleComprasType"),
            ("ventas", "detalleVentasType"),
            ("anulados", "detalleAnuladosType"),
            ("exportaciones", "detalleExportacionesType"),
        ):
            for index, (name, type_name_of, _min) in enumerate(
                xsd_particles(type_name, types)
            ):
                positions.setdefault(name, {})[block] = index
                typed.setdefault(name, {})[block] = type_name_of

        establishment = positions["establecimiento"]
        self.assertEqual(
            sorted(establishment), ["anulados", "compras", "exportaciones"]
        )
        self.assertGreater(
            len(set(establishment.values())),
            1,
            "'establecimiento' occupies a different position in each block by "
            f"construction; observed {establishment}",
        )

        self.assertEqual(typed["totalVentas"]["iva"], "totalVentasType")
        self.assertEqual(typed["ventasEstab"]["ventaEst"], "totalVentasType")
        for name in ("baseNoGraIva", "baseImponible", "baseImpGrav", "montoIva"):
            self.assertEqual(typed[name]["ventas"], "monedaType")
            self.assertEqual(typed[name]["compras"], "monedaType")
            self.assertNotEqual(typed[name]["ventas"], "totalVentasType")

    def test_the_declared_amount_typing_is_internally_consistent(self):
        """``signed`` and ``xsd_type`` cannot drift apart.

        Both are per-element declarations, so a table that got one of them wrong
        would still validate -- an amount declared ``signed=True`` while its
        ``xsd_type`` said ``monedaType`` would emit a minus into a field the schema
        refuses, and that is exactly the class of bug the per-block typing exists to
        prevent. So the two are asserted against each other for every amount in the
        document.
        """
        specs = (
            ATS_HEADER_SPEC,
            ATS_COMPRAS_SPEC,
            ATS_VENTAS_SPEC,
            ATS_VENTAS_ESTABLECIMIENTO_SPEC,
            ATS_ANULADOS_SPEC,
        )
        amounts = [
            field
            for spec in specs
            for field in spec
            if field.kind == ATS_AMOUNT and field.emitted
        ]
        self.assertTrue(amounts)
        for field in amounts:
            expected = "totalVentasType" if field.signed else "monedaType"
            self.assertEqual(
                field.xsd_type,
                expected,
                f"{field.name}: signed={field.signed} contradicts "
                f"xsd_type={field.xsd_type}",
            )
        # And the only signed amounts in the whole document are the two the ficha
        # defines: the gross total and the establishment net.
        self.assertEqual(
            sorted(field.name for field in amounts if field.signed),
            ["totalVentas", "ventasEstab"],
        )

    def test_declared_lexical_limits_match_the_shipped_schema(self):
        """Every pattern, digit budget and bound the builder carries is checked.

        The builder holds lexical constants -- ``100.5`` is not a ``monedaType``,
        ``Anio`` is ``\\d{4}`` from 2000 -- and the acceptance criterion forbids a
        value in Python that the schema or the catalogue owns. Rather than leave them
        as claims, each one is compared here against the facet the shipped XSD
        declares. A builder that drifted from the artifact, or an artifact refreshed
        under it, fails this test instead of filing a wrong file.

        These are **schema** facets, not business values: no code, rate, code list
        or date range appears among them. ``codigoOperativo`` and
        ``TipoIDInformante`` are the schema's own single-value enumerations and are
        the only literals in the builder.
        """
        self.assertEqual(
            xsd_simple_type("monedaType"),
            {
                "base": "xsd:decimal",
                "pattern": r"[0-9]{1,12}\.[0-9]{2}|[0-9]{1,12}",
                "min": "0.0",
                "max": "999999999999.99",
            },
            "the builder's unsigned amount limits must be monedaType's",
        )
        self.assertEqual(
            xsd_simple_type("totalVentasType"),
            {
                "base": "xsd:decimal",
                "pattern": (
                    r"[0-9]{1,12}\.[0-9]{2}|[0-9]{1,12}|"
                    r"[\-][0-9]{1,12}\.[0-9]{2}|[\-][0-9]{1,12}"
                ),
                "min": "",
                "max": "999999999999.99",
            },
            "the builder's signed amount limits must be totalVentasType's, "
            "including the absence of a minInclusive",
        )
        self.assertEqual(
            xsd_simple_type("fechaType")["pattern"],
            r"(0[1-9]|[12][0-9]|3[01])[/](0[1-9]|1[012])[/](19|20)\d\d",
        )
        self.assertEqual(xsd_simple_type("anioType")["min"], "2000")
        self.assertEqual(xsd_simple_type("anioType")["pattern"], r"\d{4}")
        self.assertEqual(
            xsd_simple_type("porcentajeAirType"),
            {
                "base": "xsd:decimal",
                "pattern": r"[0-9]{1,3}\.[0-9]{2}|[0-9]{1,3}",
                "min": "0.00",
                "max": "100",
            },
            "porcentajeAir allows three integer digits, not twelve -- reusing the "
            "amount limits would let a rate through that the schema refuses",
        )
        self.assertEqual(
            xsd_simple_type("valorRetBienesType")["max"], "999999999999.99"
        )
        self.assertEqual(xsd_simple_type("baseImponibleType")["min"], "0.0")

    def test_a_zero_establishment_code_is_refused_rather_than_emitted(self):
        """§5.4b: the builder refuses a ``000`` the schema would happily accept.

        ``establecimientoType`` and ``ptoEmisionType`` carry only a ``[0-9]{3}``
        pattern, so ``000`` validates on a compras row and on an anulados row -- ATS-04
        proved the acceptance. The ficha numbers establishments from ``001``, so
        emitting one produces a file that clears every grammar rule and is refused at
        reception. Refusing it here is the second line of defence §5.4b asks for;
        ATS-11 owns the authoritative preflight.
        """
        self._assert_refused(
            self._payload(compras=[self._compras_row(establecimiento="000")]),
            "establecimiento",
        )
        self._assert_refused(
            self._payload(compras=[self._compras_row(puntoEmision="000")]),
            "puntoEmision",
        )
        self._assert_refused(
            self._payload(anulados=[self._anulado_row(establecimiento="000")]),
            "establecimiento",
        )
        self._assert_refused(
            self._payload(header=self._header(numEstabRuc="000")), "numEstabRuc"
        )

    # ------------------------------------------------------------------
    # TRAP 7 -- the deprecated retencion family
    # ------------------------------------------------------------------

    def test_trap_07_the_deprecated_retencion_family_is_never_emitted(self):
        """``estabRetencion2``..``fechaEmiRet2``: *"eliminado se mantiene por
        compatibilidad"*.

        The schema still accepts them -- ATS-04 pinned that acceptance on purpose,
        so the sha256 proof of the published artifact keeps holding. But the SRI
        removed the concept and kept the elements so old files keep validating;
        emitting them in a new file is filing a field the government no longer reads.
        So the builder emits nothing, and a payload that asks for one is **refused**
        rather than silently dropped: if ATS-06 ever starts producing it, generation
        stops and somebody decides on purpose.

        The ``-1`` family is refused the same way. It is not deprecated, but no Odoo
        record describes a withholding *document*, so there is no source for it and
        no reason to reserve the elements.
        """
        document = self._assert_valid(
            self._payload(compras=[self._compras_row()]),
            "a compras row with no retencion family",
        )
        for name in (
            "estabRetencion1",
            "ptoEmiRetencion1",
            "secRetencion1",
            "autRetencion1",
            "fechaEmiRet1",
            "estabRetencion2",
            "ptoEmiRetencion2",
            "secRetencion2",
            "autRetencion2",
            "fechaEmiRet2",
        ):
            self.assertNotIn(name, document, f"{name} must never be emitted")

        for name in ("estabRetencion2", "fechaEmiRet2", "estabRetencion1"):
            self._assert_refused(
                self._payload(compras=[self._compras_row(**{name: "001"})]), name
            )
        # And the refusal says why, so the answer is in the error rather than in
        # this test file.
        message = self._assert_refused(
            self._payload(compras=[self._compras_row(fechaEmiRet2="15/03/2024")]),
            "eliminado se mantiene por compatibilidad",
        )
        self.assertIn("fechaEmiRet2", message)

    def test_the_other_out_of_scope_compras_families_are_refused_too(self):
        """``pagoExterior``, ``docModificado``, ``reembolsos``,
        ``valorRetencionNc``, ``totbasesImpReemb``.

        None of them is in v1's scope, and for a reason the builder cannot see: a
        dividend payment, a modified document, a refund and a foreign-payment box
        all need Odoo records this addon does not have (§4.2). Refusing them keeps
        the omission honest and auditable rather than a silent gap.
        """
        for name in (
            "pagoExterior",
            "docModificado",
            "reembolsos",
            "valorRetencionNc",
            "totbasesImpReemb",
        ):
            self._assert_refused(
                self._payload(compras=[self._compras_row(**{name: "00"})]), name
            )

    def test_compensaciones_and_iva_comp_are_refused(self):
        """The two ``Tabla 21`` compensation elements.

        ``Tabla 21`` **is** loaded, so this is a decision about a missing source and
        not about a missing table: nothing in Odoo records an IVA compensation, so
        ATS-07 and ATS-08 omit the elements and the builder refuses them.
        ``compensacionType`` requires a ``tipoCompe`` from that table, so a
        fabricated one would be a fabricated catalogue read.
        """
        self._assert_refused(
            self._payload(ventas=[self._ventas_row(compensaciones=[])]),
            "compensaciones",
        )
        self._assert_refused(
            self._payload(
                ventasEstablecimiento=[
                    {"codEstab": "001", "ventasEstab": 100.0, "ivaComp": 0.0}
                ]
            ),
            "ivaComp",
        )

    # ------------------------------------------------------------------
    # TRAP 8 -- the recap establishment code
    # ------------------------------------------------------------------

    def test_trap_08_establecimiento_recap_is_never_emitted(self):
        """``establecimientoRecap`` is a 2-digit ``estRecapType``, not 3.

        It is ``minExclusive 000`` and lives inside ``recap``, which is the ``Tipo 2``
        contributor's block -- the credit-card issuer. §4.1 is unambiguous that v1 is
        ``Tipo 1`` only and that the restriction is the SRI's own taxonomy rather than
        a policy choice, so ``recap`` is unreachable and ``establecimientoRecap`` with
        it.

        The builder's part is to refuse it, because the two-digit width is exactly the
        kind of detail a generalised establishment helper would get wrong: a
        three-digit ``001`` and a two-digit ``01`` are both "an establishment code",
        and emitting the wrong width produces a file the SRI refuses for a reason no
        amount of validation will explain. The width is read from the XSD rather than
        restated, so the claim stays true if the artifact is refreshed.
        """
        recap_types = {
            name: type_name
            for name, type_name, _min in xsd_particles("detalleRecapType")
        }
        self.assertIn("establecimientoRecap", recap_types)
        self.assertNotEqual(
            recap_types["establecimientoRecap"],
            recap_types["establecimiento"],
            "the trap is that the two differ at all",
        )
        recap_code = xsd_simple_type(recap_types["establecimientoRecap"])
        establishment_code = xsd_simple_type(recap_types["establecimiento"])
        self.assertEqual(recap_code["pattern"], r"[0-9]{2}")
        self.assertEqual(establishment_code["pattern"], r"\d{3}")

        document = self._assert_valid(self._payload(), "the header alone")
        self.assertNotIn("recap", document)
        self.assertNotIn("establecimientoRecap", document)
        self._assert_refused(self._payload(header=self._header(recap=[])), "recap")
        self._assert_refused(
            self._payload(header=self._header(establecimientoRecap="01")),
            "establecimientoRecap",
        )

    # ------------------------------------------------------------------
    # Blocks the payload does not carry
    # ------------------------------------------------------------------

    def test_a_block_the_payload_omits_produces_no_element(self):
        """Absent means absent, never an empty element and never a default.

        The collector withholds a block it could not fill honestly, so the builder must
        not manufacture one. An empty ``<compras/>`` would also validate
        (``detalleCompras`` is ``minOccurs="0"``), which is precisely why this has to
        be asserted: the schema cannot tell the difference between "no purchases were
        reported" and "purchases were not collected", and the SRI can.
        """
        document = self._assert_valid(
            {"header": self._header()}, "a header-only payload"
        )
        for block in ("compras", "ventas", "ventasEstablecimiento", "anulados"):
            self.assertIsNone(
                self._children_of(document, block),
                f"{block} must produce no element when the payload omits it",
            )
        self.assertEqual(self._text_of(document, "codigoOperativo"), "IVA")

    def test_an_empty_period_still_builds_a_valid_document(self):
        """Present but empty is not the same as omitted.

        A company with no purchases in the period has an **empty** purchases block,
        and ``<compras/>`` is the schema-valid way to say so. The distinction from the
        previous test is the point: ``[]`` means "collected, nothing found"; a missing
        key means "not collected".
        """
        document = self._assert_valid(
            self._payload(compras=[], ventas=[], anulados=[]), "an empty period"
        )
        for block in ("compras", "ventas", "anulados"):
            self.assertEqual(
                self._children_of(document, block),
                [],
                f"{block} was collected and is empty, so the wrapper is emitted "
                f"with no detail rows",
            )
        self.assertIn("<compras />", document)
        self.assertIn("<ventas />", document)
        self.assertIn("<anulados />", document)

    def test_an_empty_establishment_block_is_omitted_not_emitted_empty(self):
        """``ventaEst`` is ``minOccurs="1"``, so ``<ventasEstablecimiento/>`` is
        invalid.

        Three of the four block wrappers accept an empty element; this one does not,
        and the asymmetry is a schema fact rather than a style choice. The honest
        representation of zero establishments is no element -- which is also what
        ATS-08 already implies, since ``collect_iva_header`` refuses a header when the
        establishment count is zero.
        """
        document = self._assert_valid(
            self._payload(ventasEstablecimiento=[]), "an empty establishment block"
        )
        self.assertIsNone(
            self._children_of(document, "ventasEstablecimiento"),
            "an empty ventasEstablecimiento must be omitted: ventaEst is "
            "minOccurs=1, so the empty wrapper would not validate",
        )

    # ------------------------------------------------------------------
    # The header's two literals
    # ------------------------------------------------------------------

    def test_codigo_operativo_and_tipo_id_informante_hold_their_single_values(self):
        """The only two literals in the builder, and both are enumerated.

        ``codigoOperativoType`` admits ``IVA`` and nothing else; the inline type on
        ``TipoIDInformante`` admits ``R`` and nothing else. ATS-04 pinned both
        rejections. They are literals because a single-value enumeration has no other
        source -- there is no catalogue row to resolve them through.
        """
        document = self._assert_valid(
            self._payload(header=self._header(), compras=[]),
            "the enumerated header",
        )
        self.assertEqual(self._text_of(document, "codigoOperativo"), "IVA")
        self.assertEqual(self._text_of(document, "TipoIDInformante"), "R")

        self._assert_refused(
            self._payload(header=self._header(codigoOperativo="CTC")), "codigoOperativo"
        )
        self._assert_refused(
            self._payload(header=self._header(TipoIDInformante="C")), "TipoIDInformante"
        )

    def test_rounding_is_half_up_on_every_amount_not_just_the_first(self):
        """One rounding mode for the whole document.

        Checking a single amount would leave the other nineteen formatting paths free
        to differ, and ``str(float)`` is a different answer from
        ``Decimal(str(float)).quantize(...)`` for every value whose shortest
        representation is shorter than two decimals. So this walks the amounts of a
        fully populated row, including the three inside ``air``, at once.
        """
        document = self._assert_valid(
            self._payload(
                compras=[
                    self._compras_row(
                        baseNoGraIva=1.005,
                        baseImponible=2.675,
                        baseImpGrav=0.125,
                        baseImpExe=4.115,
                        montoIce=5.045,
                        montoIva=12.345,
                        air=[
                            {
                                "codRetAir": "312C",
                                "baseImpAir": 6.665,
                                "porcentajeAir": 1.755,
                                "valRetAir": 7.775,
                            }
                        ],
                    )
                ]
            ),
            "a row where every amount needs rounding",
        )
        for element, expected in (
            ("baseNoGraIva", "1.01"),
            ("baseImponible", "2.68"),
            ("baseImpGrav", "0.13"),
            ("baseImpExe", "4.12"),
            ("montoIce", "5.05"),
            ("montoIva", "12.35"),
            ("baseImpAir", "6.67"),
            ("porcentajeAir", "1.76"),
            ("valRetAir", "7.78"),
        ):
            self.assertIn(f"<{element}>{expected}</{element}>", document)

    def test_the_declaration_matches_the_repository_s_xml_canonical_form(self):
        """The document opens exactly as ATS-04's fixtures do, newline included.

        Both halves were found by ``pre-commit`` disagreeing with the builder:
        ``prettier (with plugin-xml)`` rewrites an XML declaration to put a space
        before ``?>``, and ``end-of-file-fixer`` guarantees a single trailing
        newline. A builder emitting the other form makes the hook reformat its own
        golden fixture on every run, so the emitted form is pinned instead -- and
        pinned against a fixture already committed in this directory rather than
        against a literal, so the two cannot drift apart again.
        """
        with file_open(f"{FIXTURES_PATH}/ats_valid_minimal.xml", "rb") as fixture_file:
            reference = fixture_file.read().decode("utf-8")
        self.assertEqual(
            ATS_XML_DECLARATION,
            reference.splitlines()[0],
            "the declaration must be the one ATS-04's fixtures already carry, "
            "space before the closing ?> included",
        )
        document = self._assert_valid(self._payload(), "the header alone")
        self.assertEqual(
            document.splitlines()[0],
            reference.splitlines()[0],
            "and the document must open with it",
        )
        self.assertTrue(
            document.endswith(ATS_XML_TRAILER)
            and not document.endswith(ATS_XML_TRAILER * 2),
            "the document must end in exactly one newline, which end-of-file-fixer "
            "requires of every text file in the repository and which the golden "
            "fixture comparison depends on",
        )

    def test_the_builder_is_a_pure_function_of_its_payload(self):
        """Same payload, same bytes; and the payload is not mutated.

        §6 makes purity the reason the collectors and the builder are testable
        without a database fixture, so it is worth a test rather than a claim: a
        builder that popped keys off the payload would pass every other test here and
        still be unusable, because the caller would find its rows emptied after a
        successful build.
        """
        payload = self._payload(
            compras=[self._compras_row()],
            ventas=[self._ventas_row()],
            ventasEstablecimiento=[{"codEstab": "001", "ventasEstab": 100.0}],
        )
        snapshot = repr(payload)
        first = self._assert_valid(payload, "first build")
        second = build_ats_xml(payload)
        self.assertEqual(first, second, "the builder must be deterministic")
        self.assertEqual(
            repr(payload), snapshot, "the builder must not mutate its payload"
        )
