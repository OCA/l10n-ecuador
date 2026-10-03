"""Turn collector payloads into one ATS document.

This module is the seam between :mod:`l10n_ec_ats.models.l10n_ec_ats_collector`
and the file the SRI receives. It is a **pure function** -- no ORM read, no
``self.env.cr``, no write, no transaction -- exactly as §6 of the plan requires,
and it is the reason the whole generation path is testable without a database
fixture beyond the one ``file_open`` needs to reach ``ats.xsd``.

Three rules decide everything here, and none of them is "be careful".

**Order is declared, never inherited.** The collectors return plain dicts keyed
by ATS element name. A dict is unordered, and every block of ``ivaType`` is an
``xsd:sequence``, so the order the collector happened to insert keys in is not
information. Each block therefore declares its own ordered spec,
:data:`ATS_COMPRAS_SPEC` and its siblings, and the builder walks **the spec**, not
the payload. Those specs are not a claim about the schema:
``test_trap_06_order_and_type_are_declared_per_block_and_never_flattened``
derives the content model out of the shipped ``ats.xsd`` and compares it,
element by element, position by position, type by type.

**Type is per block, so the specs cannot be flattened.** ``air``,
``establecimiento``, ``puntoEmision``, ``autorizacion``, ``secuencial``,
``montoIce``, ``anioUtDiv`` and ``fechaPagoDiv`` are the plan's §5.4 prefixed
aliases, and each one means something different depending on the block that
carries it. Two of those differences bite inside v1's own Tipo 1 scope:

* ``montoIce`` is mandatory on a compras row and optional on a ventas row;
* ``ventasEstab`` and ``totalVentas`` are ``totalVentasType`` while every other
  amount in the document is ``monedaType``.

That second one is not cosmetic -- it *is* the credit-note sign question.
``totalVentasType`` is the only amount type in the schema whose pattern admits a
leading minus, and inside Tipo 1 it carries exactly two elements. So "which
element may hold a negative" is answered by an element's own declared type, and a
single flattened ``field -> type`` map cannot answer it. A builder that kept one
global amount formatter would either reject a legitimate negative net or emit an
illegitimate one somewhere else.

**Refusal, never repair.** The collectors already refuse to substitute a value
they could not source, so anything the builder cannot represent is a broken
contract rather than a gap to paper over. A negative line amount, an amount past
the twelve integer digits ``monedaType`` allows, a two-character company name, a
``000`` establishment, an element outside v1's scope: each raises
:class:`AtsBuilderError` naming the element. Taking an absolute value, clamping a
length or truncating digits would each produce a file describing a company that
does not exist, and each of those is the substitution this addon exists to
prevent -- one layer up.

The two literals in this file are ``codigoOperativo`` and ``TipoIDInformante``,
which the plan's §4.4 and acceptance criterion 3 exempt because they are the
schema's own single-value enumerations and have no catalogue row to resolve
through. Every other value arrives in the payload.
"""

import re
import unicodedata
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from xml.etree import ElementTree

#: The declaration ATS-04's fixtures carry. Emitted verbatim rather than left to
#: the serialiser, which would write single quotes and add ``standalone``.
#:
#: The space before ``?>`` is not cosmetic: it is what this repository's own
#: ``prettier (with plugin-xml)`` hook rewrites every XML declaration to, and the
#: repository's ``end-of-file-fixer`` guarantees the trailing newline. A builder
#: emitting anything else makes ``pre-commit`` reformat its own golden fixture on
#: every run, which is how the discrepancy between the two was found. The
#: declaration and the final newline are therefore part of the document's contract,
#: and ``test_the_declaration_matches_the_repository_s_xml_canonical_form`` holds
#: them to the form already committed in this directory.
ATS_XML_DECLARATION = '<?xml version="1.0" encoding="UTF-8" ?>'

#: The trailing newline ``end-of-file-fixer`` requires of every text file here.
ATS_XML_TRAILER = "\n"

#: ``ivaType``'s name, and the indentation the golden fixtures use.
ATS_ROOT_ELEMENT = "iva"
ATS_INDENT = "    "

#: The payload key the informante's own header travels under. ``header`` and **not**
#: ``ATS_ROOT_ELEMENT``: the two are the same *word* but not the same thing, and
#: conflating them is what let the two shipped layers disagree in the first place.
#: ``iva`` names the element the header is rendered into; ``header`` names where the
#: mapping sits in a collector payload. A caller who reaches for the element name
#: gets a key the builder refuses as unknown, which is the honest failure.
ATS_HEADER_KEY = "header"

#: ``codigoOperativoType`` (ats.xsd) enumerates exactly one value and
#: ``TipoIDInformante``'s inline type enumerates exactly one. These are the two
#: literals §4.4 permits: a single-value enumeration has no catalogue row to be
#: read from, so there is nothing to resolve them through. ATS-04 pinned both
#: rejections, so a caller handing over anything else is refused here.
CODIGO_OPERATIVO = "IVA"
TIPO_ID_INFORMANTE = "R"

# -- how a declared field is rendered ------------------------------------

ATS_TEXT = "text"
ATS_CODE = "code"
ATS_DATE = "date"
ATS_AMOUNT = "amount"
ATS_INT = "int"
ATS_NESTED = "nested"
ATS_BLOCK = "block"

# -- lexical limits -------------------------------------------------------
#
# Every constant below is a **schema** facet, not a business value: no code,
# rate, code list or date range appears among them. They are read from the
# published artifact and pinned against it by
# ``test_declared_lexical_limits_match_the_shipped_schema``, so a builder that
# drifted from ``ats.xsd`` -- or an ``ats.xsd`` refreshed underneath it -- fails
# the build instead of filing a wrong file.

#: ``monedaType`` (unsigned) and ``totalVentasType`` (signed) share a pattern
#: width and a ceiling, and differ only in the two leading-minus alternatives and
#: the absence of ``minInclusive``. The builder formats both through one routine
#: and lets the declared ``signed`` flag decide whether a minus may appear.
AMOUNT_PATTERN = r"[0-9]{1,12}\.[0-9]{2}|[0-9]{1,12}"
AMOUNT_CEILING = "999999999999.99"

#: ``porcentajeAirType`` is a rate, not an amount: three integer digits, not
#: twelve, and a ceiling of 100. Reusing the amount limits would let a rate
#: through that the schema refuses.
PORCENTAJE_AIR_CEILING = "100"
PORCENTAJE_AIR_FLOOR = "0.00"

#: ``fechaType``: ``dd/mm/yyyy``, day 01-31, month 01-12, year 19xx-20xx, and
#: **no calendar check**. ``31/02/2020`` satisfies it, which is why the builder
#: validates this shape and nothing more -- inventing a calendar check would be
#: re-deriving a business rule the schema deliberately leaves to ATS-11.
DATE_PATTERN = r"(0[1-9]|[12][0-9]|3[01])[/](0[1-9]|1[012])[/](19|20)\d\d"

#: ``anioType``: ``\d{4}`` with ``minInclusive 2000``. Note the asymmetry with
#: ``fechaType``, which accepts 19xx: a 1999 period produces detail dates the
#: schema accepts and a header year it refuses. Both facts are the published
#: artifact's, and both are pinned by the tests.
ANIO_PATTERN = r"\d{4}"
ANIO_FLOOR = 2000

#: The ficha's minimum length for ``razonSocial``, from the ``Validaciones``
#: column rather than from the XSD: ``razonSocialType``'s own pattern would
#: accept ``ABC``. A length is none of the code / rate / code-list / date-range
#: values acceptance criterion 3 forbids, and ATS-11 owns the authoritative
#: business check -- the builder refuses rather than files a name the SRI
#: rejects, the same posture §5.4b asks of it for a ``000`` establishment.
#:
#: Measured on the **stripped** string. See
#: ``test_razon_social_minimum_length_is_measured_after_stripping`` for why.
RAZON_SOCIAL_MINIMUM_LENGTH = 5

#: ``denoProvType`` is ``[a-zA-Z0-9][a-zA-Z0-9\s]*`` -- same whitelist as
#: ``razonSocialType`` with no length floor. One character is the floor its
#: pattern's first class implies, and that is a schema fact, not a business one.
DENO_MINIMUM_LENGTH = 1

#: The two literals' patterns and the shapes the builder has to police because a
#: silent wrong value would surface as an unexplained libxml2 message.
RUC_PATTERN = r"[0-9]{10}001"
ESTABLISHMENT_PATTERN = r"[0-9]{3}"
SECUENCIAL_PATTERN = r"\d{1,9}"
AUTORIZACION_PATTERN = r"[0-9]{3,49}"
MONTH_PATTERN = r"(0[1-9]|1[012])"
TIPO_COMPROBANTE_PATTERN = r"\d\w\w?"
IDENTIFICATION_PATTERN = r"[0-9a-zA-Z]{3,13}"
COUNT_PATTERN = r"\d{1,12}"
CODE_2_PATTERN = r"\d{2}"
CONCEPT_CODE_PATTERN = r"[A-Za-z0-9]*"

#: ``Decimal`` rounds half-up, which is Odoo's convention and the Spanish fiscal
#: expectation. ``Decimal(str(float))`` first, so the digits the collector meant
#: survive: ``2.665`` is not representable in binary and the nearest double is
#: below it, which is exactly why the builder never touches a binary float.
TWO_DECIMALS = Decimal("0.01")

#: Enough precision that ``quantize`` cannot overflow before the ceiling check
#: gets to reject the value. The ceiling is twelve integer digits, so anything
#: longer is refused rather than rounded into range.
_QUANTIZE_PRECISION = 60

_WHITESPACE_RUN = re.compile(r"\s+")


class AtsBuilderError(ValueError):
    """The payload cannot be turned into a document the SRI would accept.

    Raised rather than repaired. Every refusal names the ATS element it is about,
    because a generation failure nobody can locate is a generation failure nobody
    fixes. The wizard layer (ATS-12) decides whether to abort the whole period or
    surface the list; the builder only reports.
    """


@dataclass(frozen=True)
class AtsField:
    """One declared element of one block.

    The dataclass is the mechanism that makes the alias trap unfalsifiable rather
    than merely avoided: ``name``, ``xsd_type``, ``min_occurs`` and ``signed`` are
    all per-element declarations, so two blocks may disagree about the same
    element name and the builder has no place to put a shared opinion.

    :param name: the ATS element name, which is also the collector's dict key.
    :param kind: one of the ``ATS_*`` constants above; how the value is rendered.
    :param xsd_type: the type name ``ats.xsd`` gives this element here. Carried
        so the specs can be compared against the artifact position by position,
        and so ``signed`` has something to contradict.
    :param min_occurs: the ``xsd:minOccurs`` of this element here. ``"1"`` makes
        the field mandatory for that block and an absent key a refusal; ``"0"``
        makes an absent key the normal case and an absent **element** the output.
        ``montoIce`` is the built-in example: mandatory on compras, optional on
        ventas.
    :param pattern: the ``xsd:pattern``, checked with ``fullmatch``. Left empty
        where the type is an enumeration, because a catalogued enumeration is a
        business code list and restating it here is exactly what acceptance
        criterion 3 forbids -- the collector resolves those through the catalog.
    :param signed: only meaningful for ``ATS_AMOUNT``. True means this element is
        a ``totalVentasType`` and may carry a leading minus.
    :param ceiling: the ``xsd:maxInclusive`` an amount may not exceed.
    :param floor: the ``xsd:minInclusive`` an amount may not fall below.
    :param code_floor: an integer lower bound for a numeric code, used by
        ``Anio`` only.
    :param minimum_length: the length floor of a ``razonSocialType`` /
        ``denoProvType`` string, measured after normalisation.
    :param no_zero: whether the ficha's "never ``000``" rule (§5.4b) applies.
    :param repeated_name: for ``ATS_NESTED``, the child element the wrapper
        repeats -- ``detalleAir`` for ``air``, ``formaPago`` for
        ``formasDePago``.
    :param children: for ``ATS_NESTED``, the ordered content model of the repeated
        child.
    :param emitted: False for an element the schema declares and this builder will
        never write. They are declared rather than omitted so the specs can be
        compared against the artifact in full, and so a payload carrying one is
        refused with :attr:`reason` instead of being silently dropped.
    :param reason: why an un-emitted element is not emitted, in words the error
        message can carry.
    """

    name: str
    kind: str
    xsd_type: str = ""
    min_occurs: str = "1"
    pattern: str = ""
    signed: bool = False
    ceiling: str = ""
    floor: str = ""
    code_floor: int = 0
    minimum_length: int = 0
    no_zero: bool = False
    repeated_name: str = ""
    children: tuple = ()
    emitted: bool = True
    reason: str = ""

    @property
    def required(self):
        """Whether this block cannot do without the element."""
        return self.min_occurs == "1"


def _amount(
    name,
    xsd_type,
    *,
    signed=False,
    min_occurs="1",
    ceiling=AMOUNT_CEILING,
    floor="",
):
    """Declare an amount element, deriving its bounds from its declared type.

    The ceiling is shared because ``monedaType`` and ``totalVentasType`` declare
    the same one, and asserting that in the constructor would be a claim the tests
    should make, not code.
    """
    return AtsField(
        name=name,
        kind=ATS_AMOUNT,
        xsd_type=xsd_type,
        min_occurs=min_occurs,
        signed=signed,
        ceiling=ceiling,
        floor=floor,
    )


def _code(name, xsd_type, pattern="", *, min_occurs="1", no_zero=False, code_floor=0):
    """Declare a plain code element."""
    return AtsField(
        name=name,
        kind=ATS_CODE,
        xsd_type=xsd_type,
        min_occurs=min_occurs,
        pattern=pattern,
        no_zero=no_zero,
        code_floor=code_floor,
    )


def _date(name="fecha", xsd_type="fechaType", *, min_occurs="1"):
    """Declare a ``fechaType`` element."""
    return AtsField(
        name=name,
        kind=ATS_DATE,
        xsd_type=xsd_type,
        min_occurs=min_occurs,
        pattern=DATE_PATTERN,
    )


def _withheld(name, xsd_type, *, reason, min_occurs="0"):
    """Declare an element the schema has and this builder will never write.

    It carries its real ``xsd_type`` and ``min_occurs`` even though the builder
    has no opinion about either, for two reasons: the specs are compared against
    ``ats.xsd`` in full, so a declared-but-unemitted element that quietly drifted
    out of the comparison would weaken the pin; and a reader comparing the spec
    against the artifact should not have to work out which entries were skipped.
    """
    return AtsField(
        name=name,
        kind=ATS_CODE,
        xsd_type=xsd_type,
        min_occurs=min_occurs,
        emitted=False,
        reason=reason,
    )


#: The reasons are the record of a deliberate omission, and they travel into the
#: error message so the answer is in the log rather than in this file.
_COMPATIBILITY_ONLY = (
    "ats.xsd annotates it 'eliminado se mantiene por compatibilidad': the SRI "
    "removed the concept and kept the elements so old files keep validating, so "
    "emitting one in a new file is filing a field nobody reads any more."
)
_NO_WITHHOLDING_DOCUMENT = (
    "it identifies a withholding document, and no Odoo record describes one, so "
    "there is no source for it and the builder will not invent the five values."
)
_V1_NOT_IN_SCOPE = (
    "it is not in v1's scope (§4.2) and the records it needs do not exist in "
    "Odoo, so there is nothing honest to put in it."
)
_NO_COMPENSATION_RECORD = (
    "Tabla 21 is loaded, so this is a decision about a missing source and not a "
    "missing table: nothing in Odoo records an IVA compensation, and "
    "compensacionType would need a tipoCompe from that table, so filling it would "
    "be a fabricated catalogue read."
)
_TIPO_TWO_ONLY = (
    "recap is the Tipo 2 contributor's block -- the credit-card issuer -- and "
    "v1 is Tipo 1 only. §4.1 derives that restriction from the SRI's own "
    "taxonomy rather than from policy, so the block is unreachable."
)
_NO_DIVIDEND_RECORD = (
    "it belongs to the dividend-payment extension of the air block and no Odoo "
    "record describes a dividend payment, so there is no source for it."
)


#: ``detalleAirComprasType`` (``ats.xsd``). It **extends** ``detalleAirType``,
#: whose four mandatory children come first, and only then the five
#: dividend-payment elements -- which is why the order below is not the order the
#: type's own children appear in the file, and why a reader that ignores
#: ``xsd:extension`` would conclude ``air`` carries none of the four.
ATS_AIR_SPEC = (
    _code("codRetAir", "codRetAirType", CONCEPT_CODE_PATTERN),
    _amount("baseImpAir", "baseImponibleType"),
    _amount(
        "porcentajeAir",
        "porcentajeAirType",
        ceiling=PORCENTAJE_AIR_CEILING,
        floor=PORCENTAJE_AIR_FLOOR,
    ),
    _amount("valRetAir", "valorRetBienesType"),
    _date("fechaPagoDiv", "fechaPagoDivType", min_occurs="0"),
    _withheld("imRentaSoc", "imRentaSocType", reason=_NO_DIVIDEND_RECORD),
    _withheld("anioUtDiv", "anioUtDivType", reason=_NO_DIVIDEND_RECORD),
    _withheld("numCajBan", "numCajBanType", reason=_NO_DIVIDEND_RECORD),
    _withheld("precCajBan", "precCajBanType", reason=_NO_DIVIDEND_RECORD),
)

#: ``formasDePagoType``: a wrapper around unbounded ``formaPago``, whose type is
#: a ``Tabla 13`` code the collector already resolved through the catalog.
#:
#: Note the shape, because ``air`` and this look alike and are not:
#: ``detalleAir`` is a **complexType**, so ``<air><detalleAir>...</detalleAir></air>``
#: nests a container. ``formaPago`` is a **simpleType**, so
#: ``<formasDePago><formaPago>01</formaPago></formasDePago>`` puts the value
#: straight in the repeated element and there is nothing to nest. A builder that
#: rendered both the same way emits ``<formaPago><formaPago>01</formaPago></formaPago>``
#: and libxml2 reports *"Element content is not allowed, because the type
#: definition is simple"* -- a real observation from this task's first green run.
ATS_FORMAS_DE_PAGO_SPEC = (_code("formaPago", "formaPagoType", CODE_2_PATTERN),)


#: ``detalleComprasType``, in its declared order. All forty-six elements, emitted
#: or not, so the spec can be compared against the artifact in full.
ATS_COMPRAS_SPEC = (
    _code("codSustento", "codSustentoType", CODE_2_PATTERN),
    _code("tpIdProv", "tpIdProvType", CODE_2_PATTERN),
    _code("idProv", "idProvType", IDENTIFICATION_PATTERN),
    _code("tipoComprobante", "tipoComprobanteCompraAnuType", TIPO_COMPROBANTE_PATTERN),
    _code("tipoProv", "tipoProvType", CODE_2_PATTERN, min_occurs="0"),
    AtsField(
        name="denoProv",
        kind=ATS_TEXT,
        xsd_type="denoProvType",
        min_occurs="0",
        minimum_length=DENO_MINIMUM_LENGTH,
    ),
    _code("parteRel", "parteRelType", min_occurs="0"),
    _date("fechaRegistro"),
    _code(
        "establecimiento", "establecimientoType", ESTABLISHMENT_PATTERN, no_zero=True
    ),
    _code("puntoEmision", "ptoEmisionType", ESTABLISHMENT_PATTERN, no_zero=True),
    _code("secuencial", "secuencialType", SECUENCIAL_PATTERN),
    _date("fechaEmision"),
    _code("autorizacion", "autorizacionType", AUTORIZACION_PATTERN),
    _amount("baseNoGraIva", "monedaType"),
    _amount("baseImponible", "monedaType"),
    _amount("baseImpGrav", "monedaType"),
    _amount("baseImpExe", "monedaType"),
    _amount("montoIce", "monedaType"),
    _amount("montoIva", "monedaType"),
    _amount("valRetBien10", "monedaType", min_occurs="0"),
    _amount("valRetServ20", "monedaType", min_occurs="0"),
    _amount("valorRetBienes", "monedaType"),
    _amount("valRetServ50", "monedaType", min_occurs="0"),
    _amount("valorRetServicios", "monedaType"),
    _amount("valRetServ100", "monedaType"),
    _withheld("valorRetencionNc", "monedaType", reason=_V1_NOT_IN_SCOPE),
    _withheld("totbasesImpReemb", "monedaType", reason=_V1_NOT_IN_SCOPE),
    _withheld("pagoExterior", "pagoExteriorType", reason=_V1_NOT_IN_SCOPE),
    AtsField(
        name="formasDePago",
        kind=ATS_NESTED,
        xsd_type="formasDePagoType",
        min_occurs="0",
        repeated_name="formaPago",
        children=ATS_FORMAS_DE_PAGO_SPEC,
    ),
    AtsField(
        name="air",
        kind=ATS_NESTED,
        xsd_type="airType",
        min_occurs="0",
        repeated_name="detalleAir",
        children=ATS_AIR_SPEC,
    ),
    _withheld(
        "estabRetencion1", "establecimientoType", reason=_NO_WITHHOLDING_DOCUMENT
    ),
    _withheld("ptoEmiRetencion1", "ptoEmisionType", reason=_NO_WITHHOLDING_DOCUMENT),
    _withheld("secRetencion1", "secRetencionType", reason=_NO_WITHHOLDING_DOCUMENT),
    _withheld("autRetencion1", "autRetencionType", reason=_NO_WITHHOLDING_DOCUMENT),
    _withheld("fechaEmiRet1", "fechaType", reason=_NO_WITHHOLDING_DOCUMENT),
    _withheld("estabRetencion2", "establecimientoType", reason=_COMPATIBILITY_ONLY),
    _withheld("ptoEmiRetencion2", "ptoEmisionType", reason=_COMPATIBILITY_ONLY),
    _withheld("secRetencion2", "secRetencionType", reason=_COMPATIBILITY_ONLY),
    _withheld("autRetencion2", "autRetencionType", reason=_COMPATIBILITY_ONLY),
    _withheld("fechaEmiRet2", "fechaType", reason=_COMPATIBILITY_ONLY),
    _withheld("docModificado", "docModificadoType", reason=_V1_NOT_IN_SCOPE),
    _withheld("estabModificado", "establecimientoType", reason=_V1_NOT_IN_SCOPE),
    _withheld("ptoEmiModificado", "ptoEmisionType", reason=_V1_NOT_IN_SCOPE),
    _withheld("secModificado", "secModType", reason=_V1_NOT_IN_SCOPE),
    _withheld("autModificado", "autModificadoType", reason=_V1_NOT_IN_SCOPE),
    _withheld("reembolsos", "reembolsosType", reason=_V1_NOT_IN_SCOPE),
)

#: ``detalleVentasType``, in its declared order. Narrower than the purchases block
#: on purpose in three places, and each narrowing is a schema fact rather than a
#: choice: there is no ``baseImpExe`` element, ``montoIce`` is optional here and
#: mandatory on compras, and the six-way ``Tabla 11`` withholding run collapses
#: into a single ``valorRetIva``.
ATS_VENTAS_SPEC = (
    _code("tpIdCliente", "tpIdClienteType", CODE_2_PATTERN),
    _code("idCliente", "idClienteType", IDENTIFICATION_PATTERN),
    _code("parteRelVtas", "parteRelType", min_occurs="0"),
    _code("tipoCliente", "tipoProvType", CODE_2_PATTERN, min_occurs="0"),
    AtsField(
        name="denoCli",
        kind=ATS_TEXT,
        xsd_type="denoProvType",
        min_occurs="0",
        minimum_length=DENO_MINIMUM_LENGTH,
    ),
    _code("tipoComprobante", "tipoComprobanteType", TIPO_COMPROBANTE_PATTERN),
    _code("tipoEmision", "tipoEmisionType"),
    _code("numeroComprobantes", "numeroComprobantesType", COUNT_PATTERN),
    _amount("baseNoGraIva", "monedaType"),
    _amount("baseImponible", "monedaType"),
    _amount("baseImpGrav", "monedaType"),
    _amount("montoIva", "monedaType"),
    _withheld("compensaciones", "compensacionesType", reason=_NO_COMPENSATION_RECORD),
    _amount("montoIce", "monedaType", min_occurs="0"),
    _amount("valorRetIva", "monedaType"),
    _amount("valorRetRenta", "monedaType"),
    AtsField(
        name="formasDePago",
        kind=ATS_NESTED,
        xsd_type="formasDePagoType",
        min_occurs="0",
        repeated_name="formaPago",
        children=ATS_FORMAS_DE_PAGO_SPEC,
    ),
)

#: ``ventaEstType``, in its declared order.
#:
#: ``ventasEstab`` is the second of the document's two ``totalVentasType``
#: elements, and it is where the credit-note sign lives: ``ESQUEMA`` row 103
#: defines the block figure as the **net** -- credit notes subtracted -- while
#: ``ESQUEMA`` row 10 defines ``totalVentas`` as the **gross**. That is the only
#: reading under which the ficha's *"la sumatoria del total de ventas por los
#: establecimientos no puede ser mayor al valor registrado en el campo total
#: ventas"* is a real constraint rather than an equality.
ATS_VENTAS_ESTABLECIMIENTO_SPEC = (
    _code("codEstab", "ventasEstabType", ESTABLISHMENT_PATTERN, no_zero=True),
    _amount("ventasEstab", "totalVentasType", signed=True),
    _withheld("ivaComp", "totalVentasType", reason=_NO_COMPENSATION_RECORD),
)

#: ``detalleAnuladosType``, in its declared order. The only block that files a
#: **range** rather than a document, and the only one whose first element is
#: ``tipoComprobante`` -- the fourth of a compras row, the sixth of a ventas row.
#: One order cannot serve both, which is the flat-map refutation stated in terms
#: of this addon's own blocks.
ATS_ANULADOS_SPEC = (
    _code("tipoComprobante", "tipoComprobanteCompraAnuType", TIPO_COMPROBANTE_PATTERN),
    _code(
        "establecimiento", "establecimientoType", ESTABLISHMENT_PATTERN, no_zero=True
    ),
    _code("puntoEmision", "ptoEmisionType", ESTABLISHMENT_PATTERN, no_zero=True),
    _code("secuencialInicio", "secuencialType", SECUENCIAL_PATTERN),
    _code("secuencialFin", "secuencialType", SECUENCIAL_PATTERN),
    _code("autorizacion", "autorizacionType", AUTORIZACION_PATTERN),
)

#: The four block wrappers, each with the element the wrapper repeats.
#:
#: ``empty_is_valid`` is read from the schema, not chosen: ``detalleCompras``,
#: ``detalleVentas`` and ``detalleAnulados`` are all ``minOccurs="0"``, so an
#: empty wrapper is the schema-valid way to say "collected, nothing found". But
#: ``ventaEst`` is ``minOccurs="1"``, so ``<ventasEstablecimiento/>`` is invalid
#: and the only honest representation of zero establishments is no element.
ATS_BLOCKS = {
    "compras": ("comprasType", "detalleCompras", ATS_COMPRAS_SPEC, True),
    "ventas": ("ventasType", "detalleVentas", ATS_VENTAS_SPEC, True),
    "ventasEstablecimiento": (
        "ventasEstablecimientoType",
        "ventaEst",
        ATS_VENTAS_ESTABLECIMIENTO_SPEC,
        False,
    ),
    "anulados": ("anuladosType", "detalleAnulados", ATS_ANULADOS_SPEC, True),
}

#: ``ivaType``'s own children, in their declared order. The three optional header
#: fields sit **between** ``Mes`` and the mandatory ``codigoOperativo``, which is
#: the sharpest form of the order trap: a builder that treats "required" as
#: "first" appends them in the wrong place and emits a sequence violation.
#:
#: This is a single ordered pass over one tuple that produces the whole document,
#: because the block wrappers are declared where ``ats.xsd`` declares them.
ATS_HEADER_SPEC = (
    _code("TipoIDInformante", "", min_occurs="1"),
    _code("IdInformante", "numeroRucType", RUC_PATTERN),
    AtsField(
        name="razonSocial",
        kind=ATS_TEXT,
        xsd_type="razonSocialType",
        minimum_length=RAZON_SOCIAL_MINIMUM_LENGTH,
    ),
    _code("Anio", "anioType", ANIO_PATTERN, code_floor=ANIO_FLOOR),
    _code("Mes", "mesType", MONTH_PATTERN),
    _code("regimenMicroempresa", "regimenSemestralType", min_occurs="0"),
    _code(
        "numEstabRuc",
        "numEstabRucType",
        ESTABLISHMENT_PATTERN,
        min_occurs="0",
        no_zero=True,
    ),
    _amount("totalVentas", "totalVentasType", signed=True, min_occurs="0"),
    _code("codigoOperativo", "codigoOperativoType"),
    AtsField(name="compras", kind=ATS_BLOCK, xsd_type="comprasType", min_occurs="0"),
    AtsField(name="ventas", kind=ATS_BLOCK, xsd_type="ventasType", min_occurs="0"),
    AtsField(
        name="ventasEstablecimiento",
        kind=ATS_BLOCK,
        xsd_type="ventasEstablecimientoType",
        min_occurs="0",
    ),
    _withheld("exportaciones", "exportacionesType", reason=_V1_NOT_IN_SCOPE),
    _withheld("recap", "recapType", reason=_TIPO_TWO_ONLY),
    _withheld("fideicomisos", "fideicomisosType", reason=_V1_NOT_IN_SCOPE),
    AtsField(name="anulados", kind=ATS_BLOCK, xsd_type="anuladosType", min_occurs="0"),
    _withheld("rendFinancieros", "rendFinancierosType", reason=_V1_NOT_IN_SCOPE),
)

#: The Tipo 2-only element that §5.4's last row is about. It is not a child of
#: ``ivaType`` -- it lives inside ``recap`` -- so it has no place in
#: :data:`ATS_HEADER_SPEC`, but it still has to be refused by name: a generalised
#: establishment helper cannot tell that a three-digit ``001`` and a two-digit
#: ``01`` are different elements, and emitting the wrong width produces a file the
#: SRI refuses for a reason no amount of validation will explain.
ATS_ESTABLECIMIENTO_RECAP_NAME = "establecimientoRecap"

#: And the reason, in the same words the error carries.
ATS_ESTABLECIMIENTO_RECAP_REASON = (
    "it is estRecapType, a two-digit code inside the recap block, not the "
    "three-digit establecimientoType; recap belongs to the Tipo 2 contributor and "
    "v1 is Tipo 1 only."
)


# ----------------------------------------------------------------------
# Value rendering
# ----------------------------------------------------------------------


def _refuse(where, field, detail):
    raise AtsBuilderError(f"{where}: {field.name} {detail}")


def _render_amount(value, field, where):
    """One amount, quantised to two decimals and range-checked against its type.

    ``Decimal(str(value))`` rather than ``Decimal(value)``: a binary float cannot
    hold the digits the collector meant, and ``Decimal(2.665)`` inherits the
    float's error instead of the decimal literal. Rounding is ``ROUND_HALF_UP``
    because that is Odoo's convention and the fiscal expectation; the difference
    from banker's rounding is visible at exactly one decimal place.

    A negative is **refused**, never made positive. Only a ``totalVentasType``
    element may be negative, and that is a per-element declaration -- taking an
    absolute value here would file a magnitude for a value the caller handed over
    and would hide a collector that regressed.
    """
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        _refuse(where, field, f"is not a number: {value!r}")
    if not amount.is_finite():
        _refuse(where, field, f"is not a finite amount: {value!r}")
    with localcontext() as context:
        context.prec = _QUANTIZE_PRECISION
        try:
            quantised = amount.quantize(TWO_DECIMALS, rounding=ROUND_HALF_UP)
        except InvalidOperation:
            _refuse(where, field, f"is too large to be an amount: {value!r}")
    if not field.signed and quantised < 0:
        _refuse(
            where,
            field,
            f"is {quantised}, and {field.xsd_type} sets minInclusive 0.0 with no "
            f"negative alternative, so a reduction is filed as a magnitude "
            f"under its own document type rather than as a sign",
        )
    if field.floor and quantised < Decimal(field.floor):
        _refuse(
            where, field, f"is {quantised}, below the {field.floor} its type declares"
        )
    if field.ceiling and quantised > Decimal(field.ceiling):
        _refuse(
            where,
            field,
            f"is {quantised}, above the {field.ceiling} its type declares. The "
            f"pattern allows twelve integer digits and no more, so the value is "
            f"refused rather than truncated",
        )
    return str(quantised)


def _render_text(value, field, where):
    """One ``razonSocialType`` / ``denoProvType`` string.

    Three steps, in this order, and the order matters:

    1. **NFKD.** Decomposes an accented letter into its base letter plus a
       combining mark, so dropping the mark is what "no accents" means. ``ñ`` is
       the case that is not an accent in that sense and behaves identically: ``n``
       plus U+0303, leaving ``n``.
    2. **Whitelist, then collapse, then trim.** Every character outside
       ``[a-zA-Z0-9\\s]`` goes -- including the dot of ``S.A.``, which is outside
       the class exactly as the accent is, which is why ATS-04 could reject a
       document whose only defect was that dot. Punctuation is **dropped, not
       replaced by a space**: replacing invents a word boundary the record never
       contained, and ``S.R.L.`` is written ``SRL`` in the Ecuadorian register
       while ``S R L`` is written nowhere. Dropping is also the weaker operation,
       so no character in the file is absent from the record.

       Collapsing and trimming come **after** the filter because neither
       ``razonSocialType`` nor ``denoProvType`` declares a ``whiteSpace`` facet,
       so XSD applies ``preserve``: a leading space reaches the pattern, whose
       first character class has no whitespace in it, and the document is refused.
       Neither would the builder want to rely on a facet that is not there.

    The length floor is then applied to what survives. See
    :data:`RAZON_SOCIAL_MINIMUM_LENGTH`.
    """
    folded = unicodedata.normalize("NFKD", str(value))
    kept = "".join(
        character
        for character in folded
        if character.isascii() and (character.isalnum() or character.isspace())
    )
    reduced = _WHITESPACE_RUN.sub(" ", kept).strip()
    if len(reduced) < field.minimum_length:
        if field.minimum_length == 1:
            _refuse(
                where,
                field,
                f"is {value!r}, which is empty once reduced to the characters "
                f"{field.xsd_type} allows",
            )
        _refuse(
            where,
            field,
            f"is {value!r}, which reduces to {reduced!r}. The ficha requires at "
            f"least {field.minimum_length} characters, measured after reduction "
            f"because that is the string that gets filed -- and measured before "
            f"it the rule would admit 'SA----' and file 'SA'",
        )
    return reduced


def _render_code(value, field, where):
    """One code element: shape, then the ficha's ``000`` rule.

    Only shapes are enforced. Where a type is an enumeration the pattern is left
    empty on purpose: ``tipoEmision``'s ``{E, F}`` and ``parteRel``'s ``{SI, NO}``
    are catalogued values the collector already resolved, and restating them here
    would be exactly the hardcoded code list acceptance criterion 3 forbids.

    A ``bool`` is refused rather than stringified. ``False`` already means "omit
    this element" upstream, and ``True`` stringifies to ``"True"`` -- which for
    ``regimenMicroempresa``, whose enumeration is ``{SI}``, produces a document the
    schema refuses with *"The value 'True' is not an element of the set {'SI'}"``.
    Observed on this task's first green run. The caller resolves the flag; the
    builder never invents the word.
    """
    if isinstance(value, bool):
        _refuse(
            where,
            field,
            f"is the boolean {value!r}. A caller that means 'yes' has to supply "
            f"the value the catalogue publishes for this element -- the builder "
            f"will not guess which, and False means omit the element rather than "
            f"emit it",
        )
    text = str(value).strip()
    if field.pattern and not re.fullmatch(field.pattern, text):
        _refuse(where, field, f"is {value!r}, which does not match {field.xsd_type}")
    if field.code_floor and text.isdigit() and int(text) < field.code_floor:
        _refuse(
            where,
            field,
            f"is {text}, and {field.xsd_type} sets minInclusive {field.code_floor}. "
            f"Note that fechaType accepts years 19xx-20xx, so a 19xx period "
            f"produces detail dates this header year would refuse",
        )
    if field.no_zero and text == "000":
        _refuse(
            where,
            field,
            "is 000. ats.xsd accepts it here -- only two of its types carry "
            "minExclusive 000 -- but the ficha numbers establishments and "
            "emission points from 001, so a 000 is a file that clears every "
            "grammar rule and is refused at reception (§5.4b)",
        )
    return text


def _render_integer(value, field, where):
    """One ``xsd:integer`` element.

    Rendered from its own digits rather than through ``int()``, because ``int()``
    on a non-integral value truncates and truncation is a substitution.
    """
    text = str(value).strip()
    if not re.fullmatch(field.pattern or COUNT_PATTERN, text):
        _refuse(where, field, f"is {value!r}, which is not a {field.xsd_type}")
    return text


def _render_date(value, field, where):
    """One ``fechaType`` element: the lexical shape and nothing else.

    ``31/02/2020`` is emitted unchanged, because ``fechaType`` has no calendar
    check and the builder is not the layer that adds one. Inventing the check here
    would be re-deriving a business rule the schema leaves to ATS-11, and it would
    refuse a document the SRI's own validator accepts.
    """
    text = str(value).strip()
    if not re.fullmatch(DATE_PATTERN, text):
        _refuse(
            where,
            field,
            f"is {value!r}, which is not fechaType's dd/mm/yyyy with a year in "
            f"19xx-20xx. Note the schema performs no calendar check, so a "
            f"lexically valid impossible date passes here and is ATS-11's to "
            f"reject",
        )
    return text


# ----------------------------------------------------------------------
# Block and document rendering
# ----------------------------------------------------------------------


def _render_row(parent, element_name, payload, spec, where):
    """Render one detail row into ``parent``, walking ``spec`` and not ``payload``.

    Two rules decide what happens to a key:

    * a key in the payload that the spec does not declare is **refused**. Ignoring
      it is how a field goes missing from a filed ATS while every test still
      passes, and the collector is what will eventually start emitting it.
    * a key the spec declares mandatory and the payload omits is **refused**.
      Absence is not a zero: inventing one would be a default the builder has no
      source for. (A schema would reject the document anyway; naming the element
      beats handing back a libxml2 line number.)

    An optional key that is absent, ``None`` or ``False`` produces **no element**
    -- never an empty one. ``minOccurs="0"`` means the element may be absent, and
    an empty element asserts a value the payload does not carry.
    """
    declared = {field.name for field in spec}
    for name in payload:
        if name not in declared:
            _refuse(
                where,
                AtsField(name=name, kind=ATS_CODE),
                "is not an element of this block in ats.xsd. A builder that "
                "ignored it would drop the field from the filed document, so it "
                "is refused instead",
            )
    element = ElementTree.SubElement(parent, element_name)
    for field in spec:
        if not field.emitted:
            if field.name in payload:
                _refuse(
                    where,
                    field,
                    f"was produced by the collector but this builder never emits "
                    f"it, because {field.reason}",
                )
            continue
        if field.name not in payload:
            if field.required:
                _refuse(
                    where,
                    field,
                    "is mandatory in ats.xsd and was not produced by the "
                    "collector. An absent element is not a zero: filling it "
                    "would be a default with no source",
                )
            continue
        value = payload[field.name]
        if value is None or value is False:
            if field.required:
                _refuse(
                    where,
                    field,
                    "is mandatory in ats.xsd and was produced empty. An absent "
                    "element is not a zero",
                )
            continue
        _render_element(element, field, value, f"{where}.{field.name}")
    return element


def _render_element(parent, field, value, where, name=None):
    """Render one declared element, dispatching on its kind.

    ``name`` overrides the element name, which the repeated-scalar case needs:
    there the element the schema names is ``formaPago`` and the field describing
    its value is also ``formaPago``, so the two coincide -- but going through the
    override keeps one code path instead of two that differ by a nesting level.
    """
    element_name = field.name if name is None else name
    if field.kind == ATS_AMOUNT:
        text = _render_amount(value, field, where)
    elif field.kind == ATS_TEXT:
        text = _render_text(value, field, where)
    elif field.kind == ATS_CODE:
        text = _render_code(value, field, where)
    elif field.kind == ATS_INT:
        text = _render_integer(value, field, where)
    elif field.kind == ATS_DATE:
        text = _render_date(value, field, where)
    elif field.kind == ATS_NESTED:
        return _render_nested(parent, field, value, where)
    else:  # pragma: no cover -- a spec typo, not a payload problem
        raise AtsBuilderError(
            f"{where}: {field.name} has unrenderable kind {field.kind}"
        )
    ElementTree.SubElement(parent, element_name).text = text


def _render_nested(parent, field, value, where):
    """Render ``air`` or ``formasDePago``: a wrapper around a repeated dict.

    Both are the same payload shape -- a list of one-key dicts -- and neither is
    expressible as a scalar, which is the flat-map refutation again in a different
    place: a single ``field -> formatter`` map has no entry for "a list of dicts
    with its own content model".

    What differs is what sits *inside* the repeated element, and it is decided by
    the repeated element's own type rather than by anything the payload says:

    * ``detalleAir`` is a ``complexType``, so ``air`` renders
      ``<detalleAir>`` per entry and fills it from the child's content model.
    * ``formaPago`` is a ``simpleType``, so ``formasDePago`` puts the value
      directly in the repeated element and there is no inner element at all.

    Nesting both the same way produces
    ``<formaPago><formaPago>01</formaPago></formaPago>``, which libxml2 refuses
    with *"Element content is not allowed, because the type definition is simple"*.
    Observed on this task's first green run, not reasoned about in advance.
    """
    if isinstance(value, dict) or not isinstance(value, (list, tuple)):
        _refuse(
            where,
            field,
            f"is {value!r}, but it wraps an unbounded list of dicts, one per "
            f"entry, and a bare dict is not that list",
        )
    wrapper = ElementTree.SubElement(parent, field.name)
    for index, entry in enumerate(value):
        place = f"{where}.{field.repeated_name}[{index}]"
        if _repeats_a_scalar(field):
            _render_repeated_scalar(wrapper, field, entry, place)
        else:
            _render_row(
                wrapper,
                field.repeated_name,
                entry,
                field.children,
                place,
            )
    return wrapper


def _repeats_a_scalar(field):
    """Whether the repeated element of ``field`` holds a value rather than children.

    Read off the declaration: the repeated element is the wrapper's only child, and
    a one-child content model whose sole member has the repeated element's own
    name is the scalar shape. Anything else is a container and gets a row.
    """
    children = field.children
    return len(children) == 1 and children[0].name == field.repeated_name


def _render_repeated_scalar(wrapper, field, entry, where):
    """Fill one repeated simple-typed element from a one-key entry dict."""
    (child,) = field.children
    if not isinstance(entry, dict) or set(entry) != {child.name}:
        _refuse(
            where,
            child,
            f"is {entry!r}, but the entry must be a dict carrying exactly "
            f"{child.name!r}, because {field.repeated_name} holds a value rather "
            f"than nested elements",
        )
    _render_element(wrapper, child, entry[child.name], where, name=field.repeated_name)


def _render_block(parent, name, rows, where):
    """Render one of the four blocks, or decide that it should not be there.

    * Absent from the payload means **no element**. The collector withholds a
      block it could not fill honestly, so manufacturing an empty one would file a
      claim the collector refused to make -- and the schema could not tell the
      difference, because ``detalleCompras`` is ``minOccurs="0"``.
    * Present but empty means the block **was** collected and held nothing, and
      the wrapper is emitted with no detail rows. That is the schema-valid way to
      say so, for three of the four blocks.
    * ``ventasEstablecimiento`` is the exception: ``ventaEst`` is ``minOccurs="1"``,
      so an empty wrapper would not validate and no element is the only honest
      representation of zero establishments.
    """
    _wrapper_type, repeated_name, spec, empty_is_valid = ATS_BLOCKS[name]
    if not isinstance(rows, (list, tuple)):
        _refuse(
            where,
            AtsField(name=name, kind=ATS_BLOCK),
            f"is {rows!r}, but a block is the list of rows its collector returned",
        )
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            _refuse(
                where,
                AtsField(name=name, kind=ATS_BLOCK),
                f"holds {row!r} at index {index}, but a row is the dict the "
                f"collector returned",
            )
    if not rows and not empty_is_valid:
        return None
    wrapper = ElementTree.SubElement(parent, name)
    for index, row in enumerate(rows):
        _render_row(
            wrapper, repeated_name, row, spec, f"{where}.{repeated_name}[{index}]"
        )
    return wrapper


def _check_header_keys(header, where):
    """Refuse a header key ``ivaType`` does not declare, and the recap code.

    ``establecimientoRecap`` gets its own message because it is not a child of
    ``ivaType`` at all -- it lives inside ``recap`` -- and because the reason it
    cannot be filed is its **width**: ``estRecapType`` is a two-digit code, where
    ``establecimientoType`` is three. A generalised establishment helper cannot
    tell those apart, and emitting the wrong width produces a file the SRI refuses
    for a reason no amount of validation will explain.
    """
    declared = {field.name for field in ATS_HEADER_SPEC}
    declared.add(ATS_ESTABLECIMIENTO_RECAP_NAME)
    for name in header:
        if name not in declared:
            _refuse(
                where,
                AtsField(name=name, kind=ATS_CODE),
                "is not a child of ivaType in ats.xsd",
            )
    if ATS_ESTABLECIMIENTO_RECAP_NAME in header:
        _refuse(
            where,
            AtsField(name=ATS_ESTABLECIMIENTO_RECAP_NAME, kind=ATS_CODE),
            f"was produced but is never emitted, because "
            f"{ATS_ESTABLECIMIENTO_RECAP_REASON}",
        )


#: The two elements whose type is a single-value enumeration, mapped to that value.
#:
#: These are the only two literals in the module, and §4.4 exempts them because a
#: one-value enumeration has no catalogue row to be read from: there is nothing to
#: resolve. ``require`` rather than assume, so a caller handing over anything else
#: is refused instead of silently overridden.
HEADER_ENUMERATED_VALUES = {
    "codigoOperativo": CODIGO_OPERATIVO,
    "TipoIDInformante": TIPO_ID_INFORMANTE,
}


def _check_header_value(field, value, where):
    """Hold a header value to its enumeration, where the type is one."""
    expected = HEADER_ENUMERATED_VALUES.get(field.name)
    if expected is not None and value != expected:
        _refuse(
            where,
            field,
            f"is {value!r}, but the schema enumerates {expected!r} and nothing "
            f"else for this element",
        )


def _header_value(header, field, where):
    """The value to render for one header scalar, or ``None`` to emit no element.

    Three cases, and the difference between them is the difference between a
    refusal and an omission:

    * an absent key on a mandatory element is **refused** -- an absent element is
      not a zero, and inventing one would be a default with no source;
    * an absent, ``None`` or ``False`` value on an optional element produces **no
      element** -- ``minOccurs="0"`` means the element may be absent, and an empty
      element asserts a value the payload does not carry;
    * an absent, ``None`` or ``False`` value on a mandatory element is **refused**,
      because the element has to be there and this is not a way to put it there.
    """
    if field.name not in header:
        if field.required:
            _refuse(
                where,
                field,
                "is mandatory in ivaType and was not supplied. An absent "
                "element is not a zero",
            )
        return None
    value = header[field.name]
    if value is None or value is False:
        if field.required:
            _refuse(
                where,
                field,
                "is mandatory in ivaType and was supplied empty. An absent "
                "element is not a zero",
            )
        return None
    _check_header_value(field, value, where)
    return value


def _render_header(root, header, payload, where):
    """Render the ``iva`` children in ``ats.xsd``'s declared order.

    One ordered pass over :data:`ATS_HEADER_SPEC` produces the whole document,
    because the four block wrappers are declared exactly where ``ivaType`` declares
    them. A builder that rendered the mandatory scalars first and appended the
    optional ones afterwards would put ``regimenMicroempresa``, ``numEstabRuc``
    and ``totalVentas`` after ``codigoOperativo``, which the sequence refuses.

    The scalars come from ``header`` -- the wizard's own fields merged with
    ``collect_iva_header()``'s ``numEstabRuc`` and ``totalVentas`` -- while the
    blocks come from the payload's own keys, one per collector. Keeping them apart
    matters: the header is a single dict describing the informante, and a block is
    a list of rows describing a period, and neither can stand in for the other.
    """
    if not isinstance(header, dict):
        _refuse(
            where,
            AtsField(name="header", kind=ATS_BLOCK),
            f"is {header!r}, but the header is the dict the wizard and "
            f"collect_iva_header produced",
        )
    _check_header_keys(header, where)
    for field in ATS_HEADER_SPEC:
        if not field.emitted:
            if field.name in header or field.name in payload:
                _refuse(
                    where,
                    field,
                    f"was produced but this builder never emits it, because "
                    f"{field.reason}",
                )
            continue
        if field.kind == ATS_BLOCK:
            if field.name in payload:
                _render_block(root, field.name, payload[field.name], field.name)
            continue
        value = _header_value(header, field, f"{where}.{field.name}")
        if value is not None:
            _render_element(root, field, value, f"{where}.{field.name}")


def ats_header(payload):
    """The informante's own header, read from a collector payload.

    **The single place the header key is decided.** :func:`build_ats_xml` and
    :func:`l10n_ec_ats.validators.validate_ats` both walk a payload for the same
    document, and for a while they read the header under different keys -- the
    builder from ``header`` and the validator from ``iva``, the element name. Every
    header rule, ``IdInformante``'s RUC check digit among them, was therefore
    evaluated against an empty header and silently reported nothing, and a caller
    had to paper over the gap by handing the validator a second view of the same
    dict. One function, one key, no alias: a mismatch can no longer exist between
    two layers, because there is only one thing left to disagree about.

    Pure and total. A payload with no header yields ``{}`` rather than raising,
    because the validator walks whatever it is given and must report the header's
    own violations rather than die on a ``KeyError``; :func:`build_ats_xml` keeps
    its own mandatory-header refusal, which is a different question and stays
    there.
    """
    if not isinstance(payload, dict):
        return {}
    header = payload.get(ATS_HEADER_KEY) or {}
    return header if isinstance(header, dict) else {}


def build_ats_xml(payload):
    """Render one ATS document from one collector payload.

    :param payload: a dict with a :data:`ATS_HEADER_KEY` (``header``) key plus
        one key per block the collector produced. ``compras`` is
        ``collect_compras()``'s rows, ``ventas`` is ``collect_ventas()``'s,
        ``ventasEstablecimiento`` is ``collect_ventas_establecimiento()``'s and
        ``anulados`` is ``collect_anulados()``'s; the header is the wizard's
        scalars merged with ``collect_iva_header()``'s ``numEstabRuc`` and
        ``totalVentas``. :func:`ats_header` is how every other layer reads it.

        **A block that is absent from the payload produces no element, and a block
        that is present but empty produces an empty one** -- with
        ``ventasEstablecimiento`` the exception, because ``ventaEst`` is
        ``minOccurs="1"``. The two are different claims and the document has to be
        able to make both.

    :return: the document as ``str``, declaration included.
    :rtype: str
    :raises AtsBuilderError: for anything the builder will not file. It never
        repairs: no absolute value, no clamp, no truncation, no invented element.
    """
    if not isinstance(payload, dict):
        raise AtsBuilderError(f"the payload must be a dict of blocks, not {payload!r}")
    known = {ATS_HEADER_KEY, *ATS_BLOCKS}
    for name in payload:
        if name not in known:
            _refuse(
                "payload",
                AtsField(name=name, kind=ATS_BLOCK),
                "is not a block of the ATS document. A builder that ignored it "
                "would drop the block from the filed document, so it is refused "
                "instead",
            )
    if ATS_HEADER_KEY not in payload:
        _refuse(
            "payload",
            AtsField(name=ATS_HEADER_KEY, kind=ATS_BLOCK),
            "is mandatory: every ATS document opens with the informante's own "
            "identification",
        )
    root = ElementTree.Element(ATS_ROOT_ELEMENT)
    _render_header(root, payload[ATS_HEADER_KEY], payload, ATS_ROOT_ELEMENT)
    ElementTree.indent(root, space=ATS_INDENT)
    body = ElementTree.tostring(root, encoding="unicode")
    return ATS_XML_DECLARATION + "\n" + body + ATS_XML_TRAILER
