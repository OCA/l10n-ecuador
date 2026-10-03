"""The ``Validaciones`` column: the business layer ``ats.xsd`` cannot be.

``Catalogo_ATS.xls`` / ``ESQUEMA TIPO 1 Y 2`` column ``J`` states a validation
rule per field, and those rules are **business** rules, not grammar. The two
layers are not interchangeable and neither is sufficient alone:

* ``ats.xsd`` declares eight enumerations in total and **none** of them is the
  VAT-rate, withholding or document-type catalogue. It also accepts
  ``establecimiento="000"`` and ``puntoEmision="000"`` on exactly the two
  carriers that matter most -- ``compras`` and ``anulados`` -- while
  ``numEstabRucType`` and ``ventasEstabType`` do carry ``minExclusive 000``.
* The ``Validaciones`` column states rules no schema can: the RUC check digit,
  the ``2000`` floor on the reported year, the ceiling ``montoIce`` may not
  pass, the share of ``montoIva`` each IVA withholding is, and the
  ``USD 1.000,00`` threshold above which a payment form is mandatory.

So this module is the second layer, and it is deliberately **pure**: it reads a
collector payload and catalogue records and returns violations. It writes
nothing, opens no cursor and holds no registry state, so a rule can be exercised
against a hand-written payload without a company, a chart of accounts or a
document -- which is what makes strict TDD practical here.

Two severities, because the source states two
--------------------------------------------

``ESQUEMA`` row 22 says ``montoIva`` differing from
``baseImpGrav x porcentajeIva`` is *"mensaje de advertencia"*; the six
IVA-withholding rows say their sum exceeding ``montoIva`` is *"la validación es
grave"*. Flattening those into one level would either block a file the SRI
accepts or let a file the SRI refuses through, so :class:`AtsViolation` carries
``severity`` and :func:`blocking` separates what stops generation from what does
not.

Precedence: the ficha's numbered prose over the ``Validaciones`` column
-------------------------------------------------------------------------

Two cells in the column contradict the ficha técnica, and in both the prose is
the one that describes a case the specification itself requires to be
expressible:

* ``secuencialFin`` says *"debe ser mayor a secuencialInicio"*; ficha §2.5 says
  *"Para anular un solo comprobante, se debe indicar este número en ambos
  campos"*. A strict ``>`` makes cancelling one document unrepresentable.
* ``totalVentas`` says *"Casillero no editable, debe ser igual a la sumatoria
  de los valores registrados en los campos baseNoGraIva, Base Imponible y
  baseimpGrav. **Solo Facturación Física F**"*; ficha §2.1 defines the field as
  *"el total de las ventas realizadas en el período informado (valor consolidado
  de todos los establecimientos del contribuyente)"* with no emission-type
  restriction, and ficha §2.3 then bounds ``ventasEstab`` by *"la sumatoria del
  total de ventas por los establecimientos no puede ser mayor al valor
  registrado en el campo total ventas"*. That ceiling is only satisfiable if
  ``totalVentas`` counts **every** sale: with any electronic invoice in the
  period, a physical-only ``totalVentas`` is exceeded by ``ventasEstab`` by
  construction, so the two cells cannot both be obeyed.

The rule this module follows is therefore: **the column governs where the ficha
is silent, and the ficha's numbered prose governs where they conflict.** The
column is a summary of the DIMM desktop tool's input screen; the ficha is the
filing specification, organised per field, and no Odoo Enterprise behaviour is
evidence for either -- Enterprise's ``ent_ats`` module reproduces the
spreadsheet's reading and filters ``tipoEmision == 'F'`` in *both*
accumulations, which makes the ficha's own ceiling vacuous.

No rate is a literal
--------------------

Every percentage is read from the SRI catalogue resolved **for the reported
period** through ``_applicable_on``, and every such read must return exactly one
entry per code: zero is a coverage hole, more than one is an overlap, and both
abort naming the table, the code and the window (§5.6 Level 3, acceptance
criterion 7). The code path that would substitute a default does not exist,
which is what makes "no hardcoded values" enforceable rather than aspirational.

:data:`RETENTION_TABLA11_CODE` is the one mapping this module cannot do without
six keys, and the reason is structural rather than a rate: it binds six named
ATS elements to six ``Tabla 11`` rows, and the **rate** it resolves is the
catalogue's. See the module's own ``tests`` -- the binding is pinned against the
loaded table, so a catalogue change fails the suite rather than passing quietly.

The RUC check digit
-------------------

:func:`ruc_check_digit` implements the two module-11 branches that could be
verified against worked examples -- the private-company and public-entity forms.
It **declines** on a natural person's RUC: the ficha requires a check digit and
never publishes the algorithm, and the two community references disagree about
that branch. A guessed digit that disagreed with the SRI's would refuse a valid
taxpayer, which is worse than declining, so ``unverifiable`` is the honest
answer and it produces no violation.
"""

import calendar
import re
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext

from .builder import ATS_ESTABLECIMIENTO_RECAP_NAME, ats_header

ATS_DATE_FORMAT = "%d/%m/%Y"

#: The two decimals every ATS amount carries, and the precision the intermediate
#: arithmetic runs at. 60 is not a magic number: it is the widest mantissa a
#: multiplication of a 12-digit amount by a 5-digit rate can need before the
#: result is quantised back to the two decimals the schema accepts.
_TWO_DECIMALS = Decimal("0.01")
_QUANTIZE_PRECISION = 60

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"

#: The severities that stop generation. A warning is *reported*, not enforced.
BLOCKING_SEVERITIES = frozenset({SEVERITY_ERROR})

#: ``ESQUEMA`` row 7, verbatim: *"El año debe corresponder a periodos del 2000
#: en adelante."* The builder also pins it as ``anioType``'s ``code_floor``, so
#: this is the first gate rather than the last.
ATS_PERIOD_YEAR_FLOOR = 2000

#: ``ESQUEMA`` row 38, verbatim: *"Obligatorio cuando sumatoria de bases
#: imponibles y montos de impuestos es mayor a USD 1.000,00"*. Strictly greater,
#: so exactly one thousand does not make a payment form mandatory.
FORM_PAYO_THRESHOLD = Decimal("1000.00")

#: The three taxable bases, and **the same three** in every cell that bounds a
#: figure by them: row 21 names *"la sumatoria de baseNoGrava, baseImponible,
#: baseImpGrav"* for ``montoIce``, row 40 names *"BASES IMPONIBLES TARIFA IVA 0,
#: TARIFA IVA DIFERENTE 0 y NO OBJETO DE IVA"* for ``baseImpAir``, and row 10
#: names *"baseNoGraIva, Base Imponible y baseimpGrav"* for ``totalVentas``.
#:
#: ``baseImpExe`` is deliberately absent. It is the fourth base
#: ``detalleComprasType`` carries, ``ventasEstab``'s block has no element for it,
#: and no cell names it -- so including it would bound three figures by a bucket
#: the specification never put in the sum.
TAXED_BASES = ("baseNoGraIva", "baseImponible", "baseImpGrav")

#: The purchase-side amounts that count towards the payment-form threshold:
#: *"sumatoria de bases imponibles y montos de impuestos"*.
PURCHASE_TAX_AMOUNTS = ("montoIva", "montoIce")

#: The three-digit establishment and emission-point elements §5.4b covers.
#: Element **names**, not SRI codes, so this list carries no business value: it
#: says which elements hold a 3-digit establishment code and nothing about what
#: that code may be.
#:
#: ``establecimientoRecap`` is absent on purpose and is not forgotten -- it is
#: ``estRecapType``, **two** digits, inside the Tipo 2 ``recap`` block, so ``00``
#: there is a different element with a different meaning. It is named explicitly
#: below so a reader can see the exclusion was deliberate.
ESTABLISHMENT_ELEMENT_NAMES = frozenset(
    {
        "numEstabRuc",
        "codEstab",
        "establecimiento",
        "puntoEmision",
        "establecimientoReemb",
        "puntoEmisionReemb",
        "estabRetencion1",
        "ptoEmiRetencion1",
        "estabRetencion2",
        "ptoEmiRetencion2",
        "estabModificado",
        "ptoEmiModificado",
    }
)
NON_ESTABLISHMENT_ELEMENT_NAMES = frozenset({ATS_ESTABLECIMIENTO_RECAP_NAME})

#: ``Tabla 11``, the IVA-withholding percentages: which ATS element carries which
#: row of the table.
#:
#: This is a **binding**, not a rate. ``data/ats_catalog_11.xml`` publishes six
#: codes and six percentages -- 9 to 10%, 10 to 20%, 1 to 30%, 11 to 50%, 2 to
#: 70% and 3 to 100% -- and six ATS elements carry one each. The element's name
#: states its share ("10%", "50%") and the catalogue states the code that
#: publishes that share for a period, so resolving the code and reading the
#: percentage out of the catalogue is what keeps the rate out of this file.
#:
#: The two entries the cell words as *"hasta"* -- ``valRetServ50`` and
#: ``valRetServ100`` -- are the ones where a share below the ceiling is within
#: the rule, so they are checked against a ceiling rather than for equality. See
#: :data:`RETENTION_UP_TO_ELEMENTS`.
RETENTION_TABLA11_CODE = {
    "valRetBien10": "9",
    "valRetServ20": "10",
    "valorRetBienes": "1",
    "valRetServ50": "11",
    "valorRetServicios": "2",
    "valRetServ100": "3",
    "valorRetencionNc": "3",
}

#: The elements the column words as *"hasta el X% del montoIva"* rather than
#: *"igual al X%"*.
RETENTION_UP_TO_ELEMENTS = frozenset(
    {"valRetServ50", "valRetServ100", "valorRetencionNc"}
)

#: The five ``air`` elements the column makes conditional on ``codRetAir``.
#:
#: **Which codes belong to which group is not held here.** The SRI catalogue
#: carries no column saying so -- ``Tabla 3.10`` reuses codes across eras, so
#: ``338`` is *"Compra local de banano a productor"* in 2016 and something else
#: in 2026 -- and acceptance criterion 3 forbids the code list as a Python
#: literal while criterion 4 permits it in ``data/`` and tests. The caller
#: supplies :class:`AirConditionalCodes`, and
#: :func:`validate_compras_row` **refuses** an ``air`` row carrying one of these
#: elements when the seam was not supplied, rather than skipping the check and
#: letting it look covered.
DIVIDEND_ELEMENTS = ("fechaPagoDiv", "imRentaSoc", "anioUtDiv")
BANANA_ELEMENTS = ("numCajBan", "precCajBan")

#: The phrase ``Tabla 4`` spells its credit-note rows with, so
#: ``formaPago``'s *"No aplica para los tipos de comprobantes Notas de Crédito
#: (04)"* resolves to the catalogue's own codes instead of this file's.
#:
#: Mirrors ``models/l10n_ec_ats_collector.py``'s constant of the same name. It
#: is not imported from there: that module declares Odoo models, and importing
#: it would make this file unimportable without a registry, which is the
#: property §6 asks for. Two constants with one value is the cheaper trade than
#: coupling a pure module to the model layer.
TABLA_4_CREDIT_NOTE_KEYWORD = "NOTA DE CR"

#: The phrase ``Tabla 2`` spells its RUC rows with, so a 13-digit check digit is
#: applied to ``idProv`` / ``idCliente`` only when the row's own identification
#: type is one the catalogue calls a RUC. Same precedent as above.
TABLA_2_RUC_KEYWORD = "RUC"

#: ``ruc_check_digit`` outcomes.
RUC_VALID = "valid"
RUC_INVALID = "invalid"
RUC_UNVERIFIABLE = "unverifiable"

#: Module 11 weights per branch, and the position (0-based) the verified digit
#: occupies. Both branches are corroborated by worked examples:
#:
#: * private company / foreign -- ``0992301287001``: weights
#:   ``[4, 3, 2, 7, 6, 5, 4, 3, 2]`` over ``099230128`` give 103, ``103 % 11`` is
#:   4, ``11 - 4`` is 7, and the tenth digit is 7.
#: * public entity -- ``1768181150001``: weights ``[3, 2, 7, 6, 5, 4, 3, 2]`` over
#:   the first eight digits give a remainder whose complement is the ninth digit.
#:
#: A natural person's RUC carries a module-10 digit instead, and the two public
#: references disagree on whether it is ``sum % 10`` or ``(10 - sum % 10) % 10``.
#: Nothing in the ficha, the XSD or the catalogue settles it, so that branch is
#: absent from this table and :func:`ruc_check_digit` declines it.
RUC_MODULE_11_BRANCHES = {
    "6": ((3, 2, 7, 6, 5, 4, 3, 2), 8),
    "9": ((4, 3, 2, 7, 6, 5, 4, 3, 2), 9),
}

#: The three digits the ficha pins: *"los tres últimos deben ser 001"*. The
#: length is carried by :data:`_RUC_DIGITS` and the suffix here, so the two live
#: next to the one place that uses them.
RUC_BRANCH_SUFFIX = "001"

_RUC_DIGITS = re.compile(r"\A[0-9]{13}\Z")
_ESTABLISHMENT_ZERO = "000"


@dataclass(frozen=True)
class AtsPeriod:
    """The month an ATS is filed for, and the day its catalogue is read on.

    Every effective-dated lookup in this module goes through
    :attr:`catalog_probe`, which is the **last day** of the reported period. That
    is the regime in force when the file is filed, and every window boundary in
    the loaded catalogue falls on the first of a month, so first-day and last-day
    resolution agree for every table shipped here. A regime that changed
    mid-month would make them disagree; that is a property of the source this
    module cannot anticipate, and it is why the probe is named rather than
    inlined.
    """

    year: int
    month: int

    def __post_init__(self):
        if not 1 <= self.month <= 12:
            raise ValueError(f"month must be 01..12, got {self.month}")

    @classmethod
    def of(cls, value):
        """Accept an :class:`AtsPeriod`, a ``date``, ``"YYYY-MM"`` or ``(y, m)``."""
        if isinstance(value, AtsPeriod):
            return value
        if isinstance(value, (date, datetime)):
            return cls(value.year, value.month)
        if isinstance(value, str):
            return cls(int(value[0:4]), int(value[5:7]))
        year, month = value
        return cls(int(year), int(month))

    @property
    def first_day(self):
        return date(self.year, self.month, 1)

    @property
    def last_day(self):
        return date(
            self.year, self.month, calendar.monthrange(self.year, self.month)[1]
        )

    @property
    def catalog_probe(self):
        return self.last_day

    @property
    def label(self):
        return f"{self.year:04d}-{self.month:02d}"


@dataclass(frozen=True)
class AtsViolation:
    """One broken rule: what it is, how bad it is, and what it was compared to.

    ``facts`` carries the numbers the message asserts, so a caller can render a
    reconciliation in a report without re-deriving it from the payload. It is a
    fresh dict built by the rule, never the caller's own mapping.
    """

    severity: str
    rule: str
    field: str
    message: str
    where: str = ""
    facts: dict = dataclass_field(default_factory=dict)

    @property
    def blocking(self):
        return self.severity in BLOCKING_SEVERITIES

    def __str__(self):
        prefix = f"{self.where}: " if self.where else ""
        return f"{prefix}{self.field} {self.message}"


def blocking(violations):
    """The violations that stop generation, in the order they were found."""
    return tuple(v for v in violations if v.severity in BLOCKING_SEVERITIES)


def warnings_of(violations):
    """The violations that are reported and do not stop generation."""
    return tuple(v for v in violations if v.severity not in BLOCKING_SEVERITIES)


@dataclass(frozen=True)
class AirConditionalCodes:
    """Which ``codRetAir`` codes carry which dividend or banana sub-report.

    Supplied by the caller because the SRI catalogue carries no column saying so.
    :func:`validate_compras_row` refuses an ``air`` row that carries one of the
    five conditional elements while this is absent, rather than skipping a check
    it cannot perform.
    """

    dividend: frozenset = frozenset()
    banana: frozenset = frozenset()

    def groups(self):
        """``{element: group name}`` for the five conditional elements."""
        mapping = {element: "dividend" for element in DIVIDEND_ELEMENTS}
        mapping.update({element: "banana" for element in BANANA_ELEMENTS})
        return mapping

    def holds(self, group, code):
        return code in (self.dividend if group == "dividend" else self.banana)


class CatalogResolutionError(ValueError):
    """A catalogue lookup returned zero entries or more than one.

    Both are refused, neither is tolerated: zero means a period nobody covers and
    more than one means two rows claiming the same day. The exception carries the
    three facts §5.6 Level 3 requires the message to name -- the **table**, the
    **code** and the **window** the lookup was for -- as attributes as well as
    in the text, so a caller can render them without parsing the message.
    """

    def __init__(self, message, *, table, code, day, found, entries=()):
        super().__init__(message)
        self.table = table
        self.code = code
        self.day = day
        self.found = found
        self.entries = tuple(entries)


CATALOG_ENTRY_MODEL = "l10n.ec.ats.catalog.entry"
#: The registry stores each table number **zero-padded**, as
#: ``l10n.ec.ats.catalog.table.code`` documents -- ``01``, ``02``, ``04`` -- so
#: these keys are the padded strings and not the ficha's bare numbers. An
#: unpadded ``"2"`` matches nothing and every lookup silently resolves to
#: nothing, which is the worst shape a lookup failure can take.
TABLA_IVA_RETENTION = "11"
TABLA_IVA_RATE = "12"
TABLA_DOCUMENT_TYPE = "04"
TABLA_IDENTIFICATION_TYPE = "02"


@dataclass(frozen=True)
class CatalogReader:
    """The only way this module reads a rate.

    Both methods go through ``_applicable_on``, so a code that changed over time
    resolves to the row in force on the day asked for and never to the newest
    one. ``Tabla 12`` code ``12`` covers three separate windows, and a flat search
    would find all three and abort a period that is perfectly covered.

    The scope is applied **after** the temporal resolution, and that ordering is
    forced rather than chosen: ``BaseModel.search`` does not preserve the calling
    recordset's domain, so ``scoped._applicable_on(day)`` re-searches the whole
    model and hands back every table at once. Intersecting afterwards is what
    keeps ``Tabla 12`` from returning the 115 entries of ``Tabla 4`` and the
    ``Tabla 20`` emission codes with it.

    The reader performs no write and opens no cursor: it is a read seam, which is
    what §6 asks of this layer.
    """

    env: object

    def _in_force(self, domain, day):
        model = self.env[CATALOG_ENTRY_MODEL]
        return model._applicable_on(day) & model.search(domain)

    def by_code(self, table_code, code, day):
        """The entries of ``(table_code, code)`` in force on ``day``."""
        return self._in_force(
            [("table_id.code", "=", table_code), ("code", "=", code)], day
        )

    def by_table(self, table_code, day):
        """Every entry of ``table_code`` in force on ``day``."""
        return self._in_force([("table_id.code", "=", table_code)], day)


def _window_of(entries, limit=4):
    """``"a..b"`` describing the windows ``entries`` claim, for the message.

    Capped, because a mis-scoped lookup that returned a whole catalogue would
    otherwise render 115 date spans into one message and make it unreadable --
    which is the opposite of naming the window.
    """
    spans = []
    for entry in entries:
        end = entry.date_end or "open"
        spans.append(f"{entry.date_start}..{end}")
    spans = sorted(spans)
    if not spans:
        return "no window"
    if len(spans) > limit:
        return ", ".join(spans[:limit]) + f" (+{len(spans) - limit} more)"
    return ", ".join(spans)


def resolve_one(reader, table_code, code, day):
    """Exactly one entry for ``(table_code, code)``, or refuse.

    The one place "returns exactly one entry" is enforced (acceptance criterion
    7). There is no fallback and no default: a caller that wants a rate has to
    resolve it, and a catalogue that cannot answer stops generation.
    """
    entries = reader.by_code(table_code, code, day)
    if len(entries) == 1:
        return entries
    reason = "no entry covers it" if not entries else "two entries claim it"
    raise CatalogResolutionError(
        f"Tabla {table_code} code {code}: {reason} on {day}, and "
        f"{len(entries)} entries were found ({_window_of(entries)}). "
        f"A rate that cannot be resolved for the reported period is never "
        f"assumed: fix the catalogue or the period.",
        table=table_code,
        code=code,
        day=day,
        found=len(entries),
        entries=entries,
    )


def resolve_regime(reader, table_code, day):
    """The single entry in force for a table that holds **one** regime at a time.

    ``Tabla 12`` is that table: its identity is its percentage, so two applicable
    entries would be two VAT regimes in force at once. Unlike
    :func:`resolve_rates` this counts the whole table rather than per code,
    because a second regime would carry a different code and still be an overlap.
    """
    entries = reader.by_table(table_code, day)
    if len(entries) == 1:
        return entries
    raise CatalogResolutionError(
        f"Tabla {table_code} holds one regime at a time and on {day} "
        f"{len(entries)} entries were found ({_window_of(entries)}), codes "
        f"{sorted({entry.code for entry in entries})}. Exactly one entry must "
        f"apply to the reported period.",
        table=table_code,
        code="|".join(sorted({entry.code for entry in entries})),
        day=day,
        found=len(entries),
        entries=entries,
    )


def resolve_rates(reader, table_code, day):
    """``{code: percentage}`` for a table that holds **many** codes at once.

    ``Tabla 11`` publishes six codes that coexist, so "exactly one entry" applies
    per code rather than to the table: zero entries for the whole table is still a
    coverage hole, and two entries under one code are still an overlap.
    """
    entries = reader.by_table(table_code, day)
    if not entries:
        raise CatalogResolutionError(
            f"Tabla {table_code}: no entry covers {day} "
            f"(the earliest window starts {_window_of(entries) or 'nowhere'}), so "
            f"no rate can be resolved for the reported period.",
            table=table_code,
            code="",
            day=day,
            found=0,
            entries=entries,
        )
    rates = {}
    for entry in entries:
        if entry.code in rates:
            raise CatalogResolutionError(
                f"Tabla {table_code} code {entry.code}: two entries claim {day} "
                f"({_window_of(entries)}). Exactly one entry must apply to the "
                f"reported period.",
                table=table_code,
                code=entry.code,
                day=day,
                found=2,
                entries=entries,
            )
        rates[entry.code] = Decimal(str(entry.percentage))
    return rates


def retention_rate(reader, field, day):
    """The ``Tabla 11`` percentage the ATS element ``field`` withholds.

    The code comes from :data:`RETENTION_TABLA11_CODE` and the percentage from
    the catalogue, resolved for ``day``. Nothing here states a rate.
    """
    code = RETENTION_TABLA11_CODE.get(field)
    if code is None:
        raise KeyError(f"{field!r} carries no Tabla 11 share")
    rates = resolve_rates(reader, TABLA_IVA_RETENTION, day)
    if code not in rates:
        raise CatalogResolutionError(
            f"Tabla {TABLA_IVA_RETENTION} code {code} (the share of {field}) has "
            f"no window covering {day}, so the rate for {field} cannot be "
            f"resolved for the reported period. Tabla 11 published "
            f"{sorted(rates)} on that day.",
            table=TABLA_IVA_RETENTION,
            code=code,
            day=day,
            found=0,
        )
    return rates[code]


def iva_rate(reader, day):
    """The ``Tabla 12`` percentage in force on ``day``."""
    return Decimal(str(resolve_regime(reader, TABLA_IVA_RATE, day).percentage))


def credit_note_codes(reader, day):
    """The ``Tabla 4`` codes the catalogue calls a credit note on ``day``.

    Resolved by the phrase the sheet spells the row with, which is the same
    precedent ``Tabla 14`` and ``Tabla 20`` follow elsewhere in this addon: the
    code that reaches the file is always the catalogue row's own, and the phrase
    is only how that row is picked out.
    """
    codes = set()
    for entry in reader.by_table(TABLA_DOCUMENT_TYPE, day):
        description = (entry.description or "").upper()
        if TABLA_4_CREDIT_NOTE_KEYWORD in description:
            codes.add(entry.code)
    return frozenset(codes)


def ruc_codes(reader, day):
    """The ``Tabla 2`` codes the catalogue calls a RUC on ``day``."""
    codes = set()
    for entry in reader.by_table(TABLA_IDENTIFICATION_TYPE, day):
        if TABLA_2_RUC_KEYWORD in (entry.description or "").upper():
            codes.add(entry.code)
    return frozenset(codes)


def ruc_check_digit(ruc):
    """Whether ``ruc`` satisfies the RUC check digit, or cannot be checked.

    :returns: :data:`RUC_VALID`, :data:`RUC_INVALID` or
        :data:`RUC_UNVERIFIABLE`. Never raises and never guesses: an input that
        is not 13 digits, or an entity branch no authoritative source publishes an
        algorithm for, is *unverifiable* rather than invalid, because a wrong
        check digit refuses a valid taxpayer.
    """
    text = str(ruc or "").strip()
    if not _RUC_DIGITS.match(text):
        return RUC_UNVERIFIABLE
    if not text.endswith(RUC_BRANCH_SUFFIX):
        return RUC_INVALID
    branch = RUC_MODULE_11_BRANCHES.get(text[2])
    if branch is None:
        return RUC_UNVERIFIABLE
    weights, verifier_index = branch
    total = sum(
        int(digit) * weight for digit, weight in zip(text, weights, strict=False)
    )
    remainder = 11 - (total % 11)
    if remainder == 11:
        remainder = 0
    return RUC_VALID if int(text[verifier_index]) == remainder else RUC_INVALID


def _money(value, field=""):
    """One ATS amount as a two-decimal :class:`~decimal.Decimal`.

    ``Decimal(str(value))`` rather than ``Decimal(value)`` for the reason
    ``builder._render_amount`` gives: a binary float carries the collector's
    rounding error, and inheriting it would make a reconciliation fail on a
    payload that is arithmetically right. An absent amount reads as
    ``0.00``, which is what the ``Validaciones`` column means by *"si no existe
    valor colocar 0.00"*.
    """
    if value is None or value == "":
        return Decimal("0.00")
    with localcontext() as context:
        context.prec = _QUANTIZE_PRECISION
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, ValueError, ArithmeticError) as error:
            raise ValueError(
                f"{field or 'amount'} is not a number: {value!r}"
            ) from error
        if not amount.is_finite():
            raise ValueError(f"{field or 'amount'} is not a finite amount: {value!r}")
        try:
            return amount.quantize(_TWO_DECIMALS, rounding=ROUND_HALF_UP)
        except InvalidOperation as error:
            raise ValueError(
                f"{field or 'amount'} is too large to compare: {value!r}"
            ) from error


def _share(amount, percentage):
    """``amount x percentage / 100`` at the two decimals the ATS files."""
    with localcontext() as context:
        context.prec = _QUANTIZE_PRECISION
        return (amount * Decimal(str(percentage)) / Decimal(100)).quantize(
            _TWO_DECIMALS, rounding=ROUND_HALF_UP
        )


def _day(value, field=""):
    """One ATS ``fechaType`` as a :class:`~datetime.date`.

    ``dd/mm/yyyy`` is the only format the document carries. A value that is not
    that is a lexical defect the builder refuses first, so this raises rather than
    inventing an interpretation.
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value).strip(), ATS_DATE_FORMAT).date()
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field or 'date'} is not dd/mm/yyyy: {value!r}") from error


def _add_one_year(day):
    """The same day one calendar year later, clamped to the shorter February."""
    try:
        return day.replace(year=day.year + 1)
    except ValueError:
        return day.replace(year=day.year + 1, day=28)


def _error(rule, field, message, where="", **facts):
    return AtsViolation(
        severity=SEVERITY_ERROR,
        rule=rule,
        field=field,
        message=message,
        where=where,
        facts=facts,
    )


def _warning(rule, field, message, where="", **facts):
    return AtsViolation(
        severity=SEVERITY_WARNING,
        rule=rule,
        field=field,
        message=message,
        where=where,
        facts=facts,
    )


# ----------------------------------------------------------------------
# Identification
# ----------------------------------------------------------------------


def _ruc_violations(value, *, field, where):
    """One violation when the check digit is wrong, none when it cannot be read.

    :data:`RUC_UNVERIFIABLE` produces **nothing**: declining to check is not a
    finding, and turning it into one would refuse every natural person's
    counterpart until the algorithm is sourced.
    """
    outcome = ruc_check_digit(value)
    if outcome == RUC_INVALID:
        return [
            _error(
                "identificacion.ruc",
                field,
                f"is {value!r}, whose check digit does not satisfy the module 11 "
                f"the ficha técnica requires of a RUC",
                where=where,
                valor=value,
            )
        ]
    return []


def _validate_row_identification(row, *, type_field, id_field, reader, period, where):
    """Apply the RUC branch only when ``Tabla 2`` calls the row's type a RUC."""
    rucs = ruc_codes(reader, period.catalog_probe)
    if not rucs:
        raise CatalogResolutionError(
            f"Tabla {TABLA_IDENTIFICATION_TYPE} publishes no RUC row on "
            f"{period.catalog_probe}, so no identification type can be resolved "
            f"for {id_field}.",
            table=TABLA_IDENTIFICATION_TYPE,
            code="",
            day=period.catalog_probe,
            found=0,
        )
    if str(row.get(type_field, "")).strip() not in rucs:
        return []
    return _ruc_violations(row.get(id_field), field=id_field, where=where)


# ----------------------------------------------------------------------
# The 000 rule -- §5.4b
# ----------------------------------------------------------------------


def _walk(node, where=""):
    """Yield ``(path, key, value)`` for every scalar in a payload tree."""
    if isinstance(node, dict):
        for key, value in node.items():
            place = f"{where}.{key}" if where else str(key)
            if isinstance(value, (dict, list, tuple)):
                yield from _walk(value, place)
            else:
                yield place, key, value
    elif isinstance(node, (list, tuple)):
        for index, value in enumerate(node):
            place = f"{where}[{index}]"
            if isinstance(value, (dict, list, tuple)):
                yield from _walk(value, place)
            else:
                yield place, index, value


def validate_estab_codes(payload):
    """No establishment or emission-point code may be ``000`` (§5.4b).

    ``establecimientoType`` and ``ptoEmisionType`` declare no bounds at all, so
    ``000`` validates on exactly the two carriers that matter most, and the
    builder's ``no_zero`` is the last gate rather than the first. The sweep is
    **name**-driven rather than value-driven so it cannot fire on an unrelated
    element that happens to read ``000`` -- ``codSustento`` and ``tipoProv`` both
    live in two-digit code spaces where ``00`` is a different question.

    ``establecimientoRecap`` is excluded by name, not by accident: it is
    ``estRecapType``, two digits, in the Tipo 2 block.
    """
    found = []
    for place, key, value in _walk(payload):
        if key in NON_ESTABLISHMENT_ELEMENT_NAMES:
            continue
        if key not in ESTABLISHMENT_ELEMENT_NAMES:
            continue
        if str(value).strip() != _ESTABLISHMENT_ZERO:
            continue
        found.append(
            _error(
                "establecimiento.no_000",
                str(key),
                "is 000. The SRI numbers establishments and emission points "
                "from 001, and ats.xsd leaves this element unconstrained, so a "
                "000 clears every grammar rule and is refused at reception",
                where=place,
                valor=value,
            )
        )
    return found


# ----------------------------------------------------------------------
# The header
# ----------------------------------------------------------------------


def validate_header(header, period, ventas_rows=(), ventas_establecimiento_rows=()):
    """The ``ivaType`` fields and the two reconciliations they are defined by.

    * ``IdInformante`` -- *"RUC: dígito verificador, 13 dígitos numéricos con 001
      al final."* Unconditional: the cell states the RUC branch and no other.
    * ``Anio`` -- *"El año debe corresponder a periodos del 2000 en adelante."*
    * ``numEstabRuc`` -- *"Mayor a 000"* and *"en caso de que el valor registrado
      difiera de los establecimientos en estado activo registrados en el RUC"*.
      The count is reconciled against the ``ventasEstablecimiento`` rows, which
      is the reconciliation the XSD cannot express: a count is not a cardinality.
    * ``totalVentas`` -- *"Casillero no editable, debe ser igual a la sumatoria de
      los valores registrados en los campos baseNoGraIva, Base Imponible y
      baseimpGrav"*, over the ``ventas`` rows.
    * ``sum(ventasEstab)`` -- ficha §2.3: *"La sumatoria del total de ventas por
      los establecimientos no puede ser mayor al valor registrado en el campo
      total ventas"*.

    ``Anio`` and ``Mes`` are also reconciled against ``period``, because a header
    describing one month while the catalogue was resolved for another is the one
    mistake this layer exists to make impossible.
    """
    period = AtsPeriod.of(period)
    header = header or {}
    found = list(
        _ruc_violations(header.get("IdInformante"), field="IdInformante", where="iva")
    )

    declared_anio = str(header.get("Anio", "")).strip()
    if declared_anio and int(declared_anio) < ATS_PERIOD_YEAR_FLOOR:
        found.append(
            _error(
                "periodo.anio",
                "Anio",
                f"is {declared_anio}, and the reported period must be "
                f"{ATS_PERIOD_YEAR_FLOOR} or later",
                where="iva",
                anio=declared_anio,
                piso=ATS_PERIOD_YEAR_FLOOR,
            )
        )
    declared_mes = str(header.get("Mes", "")).strip()
    if declared_anio and declared_mes:
        declared = (int(declared_anio), int(declared_mes))
        if declared != (period.year, period.month):
            found.append(
                _error(
                    "periodo.cabecera",
                    "Anio",
                    f"declares {declared_anio}-{declared_mes} while the catalogue "
                    f"was resolved for {period.label}",
                    where="iva",
                    declarado=period.label,
                )
            )

    num_estab = str(header.get("numEstabRuc", "")).strip()
    rows = list(ventas_establecimiento_rows)
    if num_estab:
        if num_estab == _ESTABLISHMENT_ZERO or int(num_estab) <= 0:
            found.append(
                _error(
                    "periodo.num_estab_ruc_nonzero",
                    "numEstabRuc",
                    "is 000. The ficha says it must be greater than 000, and "
                    "numEstabRucType sets minExclusive 000, so a taxpayer with no "
                    "establishment to file has no valid value here",
                    where="iva",
                    valor=num_estab,
                )
            )
        elif int(num_estab) != len(rows):
            found.append(
                _error(
                    "periodo.num_estab_ruc_recuento",
                    "numEstabRuc",
                    f"is {num_estab}, and the ventasEstablecimiento block carries "
                    f"{len(rows)} row(s). The field states the same number of "
                    f"records must be generated as establishments inscribed in "
                    f"the RUC, and a count is not a schema cardinality",
                    where="iva",
                    declarado=num_estab,
                    filas=len(rows),
                )
            )

    expected = sum(
        (
            sum(_money(row.get(base), base) for base in TAXED_BASES)
            for row in (ventas_rows or ())
        ),
        Decimal("0.00"),
    )
    if "totalVentas" in header and header["totalVentas"] not in (None, ""):
        declared_total = _money(header["totalVentas"], "totalVentas")
        if declared_total != expected:
            found.append(
                _error(
                    "total_ventas.sumatoria",
                    "totalVentas",
                    f"is {declared_total} and the sumatoria of baseNoGraIva, "
                    f"Base Imponible and baseimpGrav over the ventas block is "
                    f"{expected}. The casillero is not editable, so it can only "
                    f"be the sumatoria",
                    where="iva",
                    declarado=declared_total,
                    esperado=expected,
                )
            )
        estab_total = sum(
            (_money(row.get("ventasEstab"), "ventasEstab") for row in rows),
            Decimal("0.00"),
        )
        if estab_total > declared_total:
            found.append(
                _error(
                    "ventas_estab.tope",
                    "ventasEstab",
                    f"sums to {estab_total}, which is greater than the "
                    f"totalVentas {declared_total} of the same file. The ficha "
                    f"caps the sumatoria del total de ventas por los "
                    f"establecimientos at the total de ventas",
                    where="iva",
                    suma=estab_total,
                    total_ventas=declared_total,
                )
            )
    return found


# ----------------------------------------------------------------------
# compras
# ----------------------------------------------------------------------


def _payment_forms(row):
    """The ``formaPago`` codes of one row, in payload order.

    ``formasDePago`` is a list of one-key dicts because ``formaPago`` is a
    ``simpleType`` (``builder.ATS_FORMAS_DE_PAGO_SPEC``), and the unbounded list is
    exactly what lets a transaction report more than one payment form.
    """
    forms = []
    for entry in row.get("formasDePago") or ():
        if isinstance(entry, dict) and "formaPago" in entry:
            forms.append(str(entry["formaPago"]).strip())
    return tuple(forms)


def _payment_threshold_amount(row):
    """*"sumatoria de bases imponibles y montos de impuestos"*."""
    total = sum((_money(row.get(name), name) for name in TAXED_BASES), Decimal("0.00"))
    return total + sum(
        (_money(row.get(name), name) for name in PURCHASE_TAX_AMOUNTS),
        Decimal("0.00"),
    )


def _validate_retention_shares(row, period, reader, where, found):
    """The six ``Tabla 11`` shares, each reconciled against ``montoIva``.

    A share of ``0.00`` is **exempt**. A purchase line that withheld no IVA
    carries ``valRetBien10`` at ``0.00`` because the element is mandatory, and
    alerting that it is not 10% of ``montoIva`` on every ordinary purchase would
    train the reader to ignore alerts. A **non-zero** share is reconciled:

    * the elements the column words as *"igual al X%"* must equal it, and a
      difference is an *alerta*;
    * the elements it words as *"hasta el X%"* must not exceed it, which is the
      ceiling that word states -- below it is within the rule.
    """
    monto_iva = _money(row.get("montoIva"), "montoIva")
    declared = {}
    for element in RETENTION_TABLA11_CODE:
        raw = row.get(element)
        if raw is None or raw == "":
            continue
        amount = _money(raw, element)
        if amount == Decimal("0.00"):
            continue
        declared[element] = amount
        expected = _share(
            monto_iva, retention_rate(reader, element, period.catalog_probe)
        )
        if element in RETENTION_UP_TO_ELEMENTS:
            if amount > expected:
                found.append(
                    _warning(
                        "compras.retencion_iva_cuota",
                        element,
                        f"is {amount} and the cell allows up to {expected}, which "
                        f"is the Tabla {TABLA_IVA_RETENTION} share of "
                        f"montoIva {monto_iva}",
                        where=f"{where}.{element}",
                        monto_iva=monto_iva,
                        esperado=expected,
                        declarado=amount,
                    )
                )
        elif amount != expected:
            found.append(
                _warning(
                    "compras.retencion_iva_cuota",
                    element,
                    f"is {amount} and the Tabla {TABLA_IVA_RETENTION} share of "
                    f"montoIva {monto_iva} is {expected}. This is an alerta, not "
                    f"an error: the SRI asks to be told, not to refuse the file",
                    where=f"{where}.{element}",
                    monto_iva=monto_iva,
                    esperado=expected,
                    declarado=amount,
                )
            )
    if declared:
        total = sum(declared.values(), Decimal("0.00"))
        if total > monto_iva:
            found.append(
                _error(
                    "compras.retenciones_tope",
                    "valorRetBienes",
                    "the sumatoria de las Retenciones is "
                    f"{total}, which is greater than the Monto IVA {monto_iva}. "
                    "The cell calls this validation grave",
                    where=where,
                    suma=total,
                    monto_iva=monto_iva,
                )
            )


def _validate_air_row(entry, row, period, *, reader, air_codes, where, found):
    """One ``detalleAir`` row: the ceilings, the share, the conditional fields."""
    base = _money(entry.get("baseImpAir"), "baseImpAir")
    retained = _money(entry.get("valRetAir"), "valRetAir")
    if retained > base:
        found.append(
            _error(
                "compras.val_ret_air",
                "valRetAir",
                f"is {retained} and baseImpAir is {base}. The cell says the "
                f"withholding may not be greater than the base imponible de renta",
                where=f"{where}.valRetAir",
                base=base,
                declarado=retained,
            )
        )
    declared_rate = entry.get("porcentajeAir")
    if declared_rate not in (None, "") and retained != Decimal("0.00"):
        expected = _share(base, declared_rate)
        if retained != expected:
            found.append(
                _warning(
                    "compras.val_ret_air_cuota",
                    "valRetAir",
                    f"is {retained} and baseImpAir {base} at porcentajeAir "
                    f"{declared_rate} is {expected}. This is an alerta",
                    where=f"{where}.valRetAir",
                    base=base,
                    esperado=expected,
                    declarado=retained,
                )
            )

    code = str(entry.get("codRetAir", "")).strip()
    groups = (air_codes or AirConditionalCodes()).groups()
    for element, group in groups.items():
        if element not in entry or entry[element] in (None, ""):
            continue
        if air_codes is None:
            raise ValueError(
                f"{where}.{element} is present on codRetAir {code}, so the "
                f"conditional-emission rule has to be checked, but the air_codes "
                f"seam was not supplied. Pass an AirConditionalCodes built from "
                f"the SRI catalogue: it carries no column saying which codes need "
                f"a dividend or a banana sub-report, so the groups cannot be "
                f"derived here, and refusing is the only honest answer to a check "
                f"that cannot be made."
            )
        if not air_codes.holds(group, code):
            found.append(
                _error(
                    "air.emision_condicional",
                    element,
                    f"is present on codRetAir {code}, which is not one of the "
                    f"{group} codes the caller resolved from the catalogue. The "
                    f"cell deploys {element} only for those codes",
                    where=f"{where}.{element}",
                    codigo=code,
                    grupo=group,
                )
            )
    if "fechaPagoDiv" in entry and entry["fechaPagoDiv"] not in (None, ""):
        paid = _day(entry["fechaPagoDiv"], "fechaPagoDiv")
        if paid > period.last_day:
            found.append(
                _error(
                    "air.fecha_pago_div",
                    "fechaPagoDiv",
                    f"is {paid}, after the reported period ends on {period.last_day}",
                    where=f"{where}.fechaPagoDiv",
                    periodo=period.label,
                )
            )
    if "anioUtDiv" in entry and entry["anioUtDiv"] not in (None, ""):
        year = int(str(entry["anioUtDiv"]).strip())
        if year > period.year:
            found.append(
                _error(
                    "air.anio_ut_div",
                    "anioUtDiv",
                    f"is {year}, later than the reported year {period.year}",
                    where=f"{where}.anioUtDiv",
                    periodo=period.label,
                )
            )
    if "imRentaSoc" in entry and entry["imRentaSoc"] not in (None, ""):
        tax = _money(entry["imRentaSoc"], "imRentaSoc")
        if tax > base:
            found.append(
                _warning(
                    "air.im_renta_soc",
                    "imRentaSoc",
                    f"is {tax}, above the baseImpAir {base}. The cell calls this "
                    f"an advertencia",
                    where=f"{where}.imRentaSoc",
                    base=base,
                    declarado=tax,
                )
            )


def validate_compras_row(row, period, *, reader, air_codes=None, where="compras"):
    """One ``detalleCompras`` row against every rule that applies to it."""
    period = AtsPeriod.of(period)
    found = []
    found.extend(
        _validate_row_identification(
            row,
            type_field="tpIdProv",
            id_field="idProv",
            reader=reader,
            period=period,
            where=where,
        )
    )

    # Period: fechaRegistro must describe the reported month, and fechaEmision must
    # sit inside the window the ficha gives it -- not after the registration date,
    # not more than a year before it, and not after the reported period ends.
    try:
        registered = _day(row.get("fechaRegistro"), "fechaRegistro")
    except ValueError as error:
        found.append(
            _error("fecha_registro.legible", "fechaRegistro", str(error), where=where)
        )
        registered = None
    emitted = None
    try:
        emitted = _day(row.get("fechaEmision"), "fechaEmision")
    except ValueError as error:
        found.append(
            _error("fecha_emision.legible", "fechaEmision", str(error), where=where)
        )
    if registered and (registered.year, registered.month) != (
        period.year,
        period.month,
    ):
        found.append(
            _error(
                "fecha_registro.periodo",
                "fechaRegistro",
                f"is {registered}, and the reported period is {period.label}. A "
                f"different period is an error",
                where=where,
                periodo=period.label,
            )
        )
    if emitted and registered:
        if emitted > registered:
            found.append(
                _error(
                    "fecha_emision.registro",
                    "fechaEmision",
                    f"is {emitted}, after the fechaRegistro {registered}",
                    where=where,
                )
            )
        ceiling = _add_one_year(emitted)
        if registered > ceiling:
            found.append(
                _error(
                    "fecha_emision.anio",
                    "fechaEmision",
                    f"is {emitted} and fechaRegistro is {registered}, beyond the "
                    f"one-year window that ends on {ceiling}",
                    where=where,
                    vencimiento=ceiling,
                )
            )
    if emitted and emitted > period.last_day:
        found.append(
            _error(
                "fecha_emision.periodo",
                "fechaEmision",
                f"is {emitted}, after the reported period ends on {period.last_day}",
                where=where,
                periodo=period.label,
            )
        )

    bases = sum((_money(row.get(name), name) for name in TAXED_BASES), Decimal("0.00"))
    ice = _money(row.get("montoIce"), "montoIce")
    if ice > bases:
        found.append(
            _error(
                "compras.monto_ice",
                "montoIce",
                f"is {ice}, greater than the sumatoria of baseNoGrava, "
                f"baseImponible and baseImpGrav, which is {bases}",
                where=where,
                bases=bases,
                declarado=ice,
            )
        )

    base_gravada = _money(row.get("baseImpGrav"), "baseImpGrav")
    monto_iva = _money(row.get("montoIva"), "montoIva")
    if monto_iva > base_gravada:
        found.append(
            _error(
                "compras.monto_iva_tope",
                "montoIva",
                f"is {monto_iva}, greater than baseImpGrav {base_gravada}",
                where=where,
                base=base_gravada,
                declarado=monto_iva,
            )
        )
    expected_iva = _share(base_gravada, iva_rate(reader, period.catalog_probe))
    if monto_iva != expected_iva:
        found.append(
            _warning(
                "compras.monto_iva",
                "montoIva",
                f"is {monto_iva} and baseImpGrav {base_gravada} at the "
                f"Tabla {TABLA_IVA_RATE} rate in force on "
                f"{period.label} is {expected_iva}. The cell asks for a "
                f"mensaje de advertencia",
                where=where,
                base=base_gravada,
                esperado=expected_iva,
                declarado=monto_iva,
            )
        )

    _validate_retention_shares(row, period, reader, where, found)

    for index, entry in enumerate(row.get("air") or ()):
        air_where = f"{where}.air[{index}]"
        air_base = _money(entry.get("baseImpAir"), "baseImpAir")
        if air_base > bases:
            found.append(
                _error(
                    "compras.base_imp_air",
                    "baseImpAir",
                    f"is {air_base}, greater than the sumatoria of the purchase "
                    f"bases, which is {bases}",
                    where=air_where,
                    bases=bases,
                    declarado=air_base,
                )
            )
        elif air_base < bases:
            found.append(
                _warning(
                    "compras.base_imp_air_inferior",
                    "baseImpAir",
                    f"is {air_base}, below the sumatoria of the purchase bases, "
                    f"which is {bases}. The cell asks for a mensaje de advertencia",
                    where=air_where,
                    bases=bases,
                    declarado=air_base,
                )
            )
        _validate_air_row(
            entry,
            row,
            period,
            reader=reader,
            air_codes=air_codes,
            where=air_where,
            found=found,
        )

    credit_notes = credit_note_codes(reader, period.catalog_probe)
    threshold_amount = _payment_threshold_amount(row)
    forms = _payment_forms(row)
    is_credit_note = str(row.get("tipoComprobante", "")).strip() in credit_notes
    if not is_credit_note and threshold_amount > FORM_PAYO_THRESHOLD and not forms:
        found.append(
            _error(
                "compras.forma_pago_obligatoria",
                "formasDePago",
                f"is empty and the sumatoria de bases imponibles y montos de "
                f"impuestos is {threshold_amount}, above the USD "
                f"{FORM_PAYO_THRESHOLD} the cell makes a forma de pago mandatory "
                f"above",
                where=where,
                monto=threshold_amount,
                umbral=FORM_PAYO_THRESHOLD,
            )
        )
    duplicates = sorted({form for form in forms if forms.count(form) > 1})
    if duplicates:
        found.append(
            _error(
                "compras.forma_pago_duplicada",
                "formasDePago",
                f"reports {duplicates} more than once. A transaction may carry "
                f"more than one forma de pago, but the same code twice is one "
                f"form written twice, and formaPagoType's unbounded repetition "
                f"cannot mean it is legal",
                where=where,
                duplicados=duplicates,
            )
        )
    return found


# ----------------------------------------------------------------------
# ventas
# ----------------------------------------------------------------------


def validate_ventas_row(row, period, *, reader, where="ventas"):
    """One ``detalleVentas`` row.

    ``montoIce`` -- *"No debe ser mayor a baseImpGrav"*.
    ``montoIva`` -- *"Debe ser igual a la baseImpGrav aplicando el porcentajeIva
    (tabla 12). Si difiere en mas o menos generar mensaje de advertencia"*.
    ``valorRetIva`` -- *"Debe ser igual a la baseImpGrav aplicando el
    porcentajeIva (tabla 11). El valor puede ser mayor o igual, si no existe
    valor colocar 0.00"*.

    **The last cell contradicts a floor reading inside one sentence.** Read
    *"el valor puede ser mayor o igual"* as a lower bound and the sanctioned
    ``0.00`` of *"si no existe valor colocar 0.00"* becomes an error whenever
    ``baseImpGrav`` is non-zero -- the two clauses cannot both hold. And the
    consequence is not academic: a floor on the lowest ``Tabla 11`` share refuses
    **every sale whose client withheld nothing**, which is most sales, so a
    company could not file a sales period at all and the message would blame the
    company rather than the rule.

    So *"puede ser mayor o igual"* is read for what it is for -- **over-withholding
    is tolerated** -- and not as a bound on the field. Three cases follow:

    * ``0.00`` is what the cell says to file when there is no withholding, so it
      produces no finding at all. The ``air`` block already reads its own
      withholding the same way: :func:`_validate_air_row` exempts a ``valRetAir``
      of ``0.00`` rather than reconciling it against ``porcentajeAir``.
    * a value equal to ``baseImpGrav`` times one ``Tabla 11`` share **in force for
      the reported period** is the cell's own product and is clean.
    * anything else is a ``SEVERITY_WARNING``. The row aggregates every
      client-side withholding for one client and document type, so a blend of
      regimes legitimately matches no single share, and exceeding a share is
      precisely what the *"may be greater or equal"* clause tolerates -- so it is
      reported and never blocked.

    **There is no grave branch left on this field.** The shares are resolved
    through :func:`resolve_rates` for the period, so the comparison is against the
    percentages the SRI published then and never against a literal.
    """
    period = AtsPeriod.of(period)
    found = []
    if "idCliente" in row:
        # The cell states one branch per identification type, exactly as
        # ``idProv`` does, so the branch is chosen from ``Tabla 2`` rather than
        # assumed. A consumer final and a plate are neither, and neither is a
        # candidate for a RUC module 11.
        found.extend(
            _validate_row_identification(
                row,
                type_field="tpIdCliente",
                id_field="idCliente",
                reader=reader,
                period=period,
                where=where,
            )
        )
    base_gravada = _money(row.get("baseImpGrav"), "baseImpGrav")
    ice = _money(row.get("montoIce"), "montoIce")
    if ice > base_gravada:
        found.append(
            _error(
                "ventas.monto_ice",
                "montoIce",
                f"is {ice}, greater than baseImpGrav {base_gravada}",
                where=where,
                base=base_gravada,
                declarado=ice,
            )
        )
    monto_iva = _money(row.get("montoIva"), "montoIva")
    expected_iva = _share(base_gravada, iva_rate(reader, period.catalog_probe))
    if monto_iva != expected_iva:
        found.append(
            _warning(
                "ventas.monto_iva",
                "montoIva",
                f"is {monto_iva} and baseImpGrav {base_gravada} at the "
                f"Tabla {TABLA_IVA_RATE} rate in force on {period.label} is "
                f"{expected_iva}",
                where=where,
                base=base_gravada,
                esperado=expected_iva,
                declarado=monto_iva,
            )
        )
    withheld = _money(row.get("valorRetIva"), "valorRetIva")
    if withheld:
        # Zero is not reconciled at all: it is what the cell says to file when the
        # client withheld nothing, so there is no product to disagree with.
        rates = resolve_rates(reader, TABLA_IVA_RETENTION, period.catalog_probe)
        shares = sorted(_share(base_gravada, rate) for rate in rates.values())
        if withheld not in shares:
            found.append(
                _warning(
                    "ventas.valor_ret_iva",
                    "valorRetIva",
                    f"is {withheld}, which matches none of the Tabla "
                    f"{TABLA_IVA_RETENTION} shares of baseImpGrav "
                    f"{base_gravada} ({shares}) in force on {period.label}. A "
                    f"blend of regimes and a value above a share are both "
                    f"allowed by the cell -- it says the value may be greater or "
                    f"equal -- so this is an alerta and never a grave finding",
                    where=where,
                    base=base_gravada,
                    declared_shares=shares,
                    declarado=withheld,
                )
            )
    forms = _payment_forms(row)
    duplicates = sorted({form for form in forms if forms.count(form) > 1})
    if duplicates:
        found.append(
            _error(
                "ventas.forma_pago_duplicada",
                "formasDePago",
                f"reports {duplicates} more than once. A transaction may carry "
                f"more than one forma de pago, but the same code twice is one "
                f"form written twice",
                where=where,
                duplicados=duplicates,
            )
        )
    return found


# ----------------------------------------------------------------------
# The whole file
# ----------------------------------------------------------------------


def validate_ats(payload, period, *, env, air_codes=None):
    """Every in-scope block of one payload, in the order the document declares.

    Five blocks are walked -- the ``iva`` header, ``compras``, ``ventas``,
    ``ventasEstablecimiento`` and ``anulados``. The last carries no rule of its
    own beyond the ``000`` sweep: ``ESQUEMA`` row 151's *"debe ser mayor a
    secuencialInicio"* is the one cell the ficha contradicts, and a range of one
    document is a case the ficha §2.5 requires to be expressible, so the range is
    left to the collector that builds it. ``exportaciones``, ``recap``,
    ``fideicomisos`` and ``rendFinancieros`` are withheld by the builder (§4.2),
    so walking them would be walking elements that cannot be present.

    The header comes from :func:`~l10n_ec_ats.builder.ats_header` -- **the same
    accessor :func:`~l10n_ec_ats.builder.build_ats_xml` uses** -- so the two
    layers cannot read the header under different keys. They once did, and every
    rule in :func:`validate_header` below, ``IdInformante``'s RUC check digit
    included, was then evaluated against an empty mapping and reported nothing.

    The ``000`` sweep runs first and over the whole tree, because it is the rule
    that decides whether a document may be filed at all and its answer changes how
    every other field should be read.
    """
    period = AtsPeriod.of(period)
    reader = CatalogReader(env)
    payload = payload or {}
    found = list(validate_estab_codes(payload))
    found.extend(
        validate_header(
            ats_header(payload),
            period,
            payload.get("ventas") or (),
            payload.get("ventasEstablecimiento") or (),
        )
    )
    for index, row in enumerate(payload.get("compras") or ()):
        found.extend(
            validate_compras_row(
                row,
                period,
                reader=reader,
                air_codes=air_codes,
                where=f"compras[{index}]",
            )
        )
    for index, row in enumerate(payload.get("ventas") or ()):
        found.extend(
            validate_ventas_row(row, period, reader=reader, where=f"ventas[{index}]")
        )
    return found
