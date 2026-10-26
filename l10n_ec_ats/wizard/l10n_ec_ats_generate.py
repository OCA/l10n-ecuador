"""The generation wizard: the one seam a user can reach.

Four layers ship before this file -- ``l10n.ec.ats.collector`` reads records into
block payloads, :mod:`~l10n_ec_ats.builder` renders those payloads into XML,
:mod:`~l10n_ec_ats.validators` applies the business rules the schema cannot
express, and :mod:`~l10n_ec_ats.schema` checks the result against ``ats.xsd``.
None of them is reachable by a user, so none of them can be proven to work on a
company's real data. This model composes them:

    wizard -> collectors -> validators -> builder -> validate_ats_xml -> zip

What it adds is the two properties the individual layers cannot have on their
own.

**Every catalog read is resolved for the reported period, and must return
exactly one entry.** Zero is a coverage hole, more than one is an overlap, and
both stop generation naming the table, the code and the window. There is no
fallback path and no default: the code that would substitute a literal does not
exist, which is what makes "no hardcoded values" enforceable rather than
aspirational. §5.6 Level 3 and acceptance criterion 7.

**Every problem is aggregated into a single** ``UserError``. One error per
lookup would make a bad period unreadable -- somebody fixing March would run
generation twenty times to see twenty problems -- and a *file* that quietly
omits the twenty unusable documents is exactly the failure acceptance criterion
6 forbids. So the collectors' per-document errors, the header's errors, the
catalog problems and the blocking violations all travel into one message, and
generation aborts.

The period field is the other gate. ``Catalogo_ATS.xls`` / ``ESQUEMA TIPO 1 Y 2``
says *"El año debe corresponder a periodos del 2000 en adelante"* and the ficha's
``ESQUEMA`` adds *"Programa despliega calendario 2000 en adelante"*, so the
field refuses an earlier year before a single record is read.

Where the ``_applicable_on`` trap bites
--------------------------------------

``l10n.ec.temporal._applicable_on`` is ``@api.model`` and calls ``self.search``.
Odoo's ``search`` does **not** carry the calling recordset's domain, so
``scoped_recordset._applicable_on(day)`` re-searches the **whole model** and
returns every row of every table -- the 115 entries of ``Tabla 04`` handed back
as though they were ``Tabla 12``. Every catalog read below therefore resolves
against the **model** and intersects the result afterwards, which is the same
ordering :class:`~l10n_ec_ats.validators.CatalogReader` and
:meth:`~l10n_ec_ats.models.l10n_ec_ats_collector.L10nEcAtsCollector.
_l10n_ec_applicable_entries` use, and for the same reason. A lookup that
intersects *before* resolving discards the temporal filter instead and hands
back every era of every concept at once.

The zero-padding trap
---------------------

``l10n.ec.ats.catalog.table.code`` stores every table number zero-padded
(``"02"``, ``"04"``, ``"13"``), and so do the entry codes of ``Tabla 01``,
``Tabla 02``, ``Tabla 05`` and ``Tabla 13``. ``Tabla 04`` and ``Tabla 11`` store
theirs **unpadded** (``"1"``, ``"9"``, ``"10"``). An unpadded table number
matches nothing, and a lookup that matches nothing resolves to *absent* rather
than raising -- the worst shape a lookup failure can take, because a rate
silently becomes "no rate" instead of an error. The table numbers are therefore
taken from :mod:`~l10n_ec_ats.validators`, which carries them padded, and the
entry-code comparison reuses the collector's own
:meth:`~l10n_ec_ats.models.l10n_ec_ats_collector.L10nEcAtsCollector.
_l10n_ec_same_code`, so there is one rule about padding in the addon rather than
two.
"""

import io
import zipfile

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

from ..builder import CODIGO_OPERATIVO, TIPO_ID_INFORMANTE, build_ats_xml
from ..schema import validate_ats_xml
from ..validators import (
    ATS_PERIOD_YEAR_FLOOR,
    TABLA_DOCUMENT_TYPE,
    TABLA_IDENTIFICATION_TYPE,
    TABLA_IVA_RATE,
    TABLA_IVA_RETENTION,
    AirConditionalCodes,
    AtsPeriod,
    CatalogReader,
    CatalogResolutionError,
    blocking,
    credit_note_codes,
    resolve_one,
    resolve_rates,
    resolve_regime,
    ruc_codes,
    validate_ats,
    warnings_of,
)

#: ``Tabla 01`` is the period table: twelve rows, one per month, whose codes are
#: the two-digit ``Mes`` the document carries. The table number is padded, like
#: every other in the registry.
TABLA_PERIOD = "01"

#: ``Tabla 05``, the tax supports, and ``Tabla 13``, the payment forms. Both
#: padded, and so are the codes ``l10n_ec_tax_support`` and
#: ``l10n_ec.sri.payment`` capture.
TABLA_TAX_SUPPORT = "05"
TABLA_PAYMENT_FORM = "13"

#: ``TABLA_PAYMENT_FORM`` is read by the collectors -- a payment form belongs to
#: a transaction, so it is resolved there and reported against the document that
#: carries it. The name is kept here so the table this module owns is visible
#: where the others are, and so a reader can see the split rather than infer it.

#: ``Tabla 3.10`` is the one referential table with no registry row: it is
#: genuinely relational and split across a concept model and a dated rate model
#: rather than being a generic entry row, so it carries the name here for the
#: message instead of a table code.
TABLA_INCOME_WITHHOLDING = "3.10"

#: The word ``Tabla 01`` spells a semestral regime with. Its rows for June and
#: December read *"Junio / I Semestre (régimen RIMPE)"* and *"Diciembre / II
#: Semestre (régimen RIMPE)"*; the other ten name a plain month.
#:
#: A description keyword rather than a code, following
#: :data:`~l10n_ec_ats.validators.TABLA_4_CREDIT_NOTE_KEYWORD` and the collector's
#: ``TABLA_20`` / ``TABLA_14`` seams for the same reason: the code that reaches
#: the file is always the catalogue row's own, and the word is only how that row
#: is picked out. A literal ``{06, 12}`` would be a code list owned by this file,
#: which acceptance criterion 3 forbids.
TABLA_1_SEMESTRAL_KEYWORD = "SEMESTRE"

#: The archive and its single member. Ficha técnica §1.2: ``AT{mmaaaa}.zip``,
#: ``mm`` the month and ``aaaa`` the year, so March 2026 is ``AT032026.zip``, and
#: *"En el nombre del archivo no se permite caracteres especiales"* -- no
#: separator, no space, no accent. The member takes the same stem: one XML
#: inside, and nothing else.
ATS_ARCHIVE_PREFIX = "AT"
ATS_ARCHIVE_SUFFIX = ".zip"
ATS_MEMBER_SUFFIX = ".xml"
ATS_ARCHIVE_MIMETYPE = "application/zip"


class L10nEcAtsGenerate(models.TransientModel):
    """Generate one month's ATS for one company, as a downloadable archive."""

    _name = "l10n.ec.ats.generate"
    _description = "Generate the monthly SRI ATS file"

    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        string="Company",
        help="The taxpayer the ATS identifies. Every block is collected for "
        "this company alone: an ATS is filed by one taxpayer, and the "
        "establishments it counts are that taxpayer's own.",
    )
    anio = fields.Integer(
        string="Year",
        required=True,
        default=lambda self: fields.Date.context_today(self).year,
        help="Reported year. ``Catalogo_ATS.xls`` / ``ESQUEMA TIPO 1 Y 2`` row 7: "
        '*"El año debe corresponder a periodos del 2000 en adelante"*, so an '
        "earlier year is refused here rather than discovered in the document.",
    )
    mes = fields.Integer(
        string="Month",
        required=True,
        default=lambda self: fields.Date.context_today(self).month,
        help="Reported month, 1 to 12. The code that reaches the file is the "
        "``Tabla 01`` row's own, read from the catalog for the reported year, so "
        "the month is captured as a number and resolved -- never formatted from "
        "a list this module owns.",
    )
    warnings = fields.Text(
        readonly=True,
        help="Findings that were reported and did **not** stop generation, "
        "written by the Generate button. ATS-11 splits its findings in two: a "
        "grave one refuses the file, and an *alerta* is reported because the SRI "
        "may question it even though it will not reject the return.\n\n"
        "Nothing is listed here when the period is clean, and a finding never "
        "appears here if it stopped generation -- that one arrives as the refusal "
        "itself, which lists every problem it found rather than the first.",
    )

    # ------------------------------------------------------------------
    # The period
    # ------------------------------------------------------------------

    @api.constrains("anio", "mes")
    def _check_period(self):
        """Refuse a period the specification does not have.

        Two independent refusals, and the second is not implied by the first:
        ``ESQUEMA``'s ``2000`` floor is about the **year**, while the month is
        bounded by ``mesType``'s own pattern. ``AtsPeriod`` raises on a month
        outside 1..12 when the period is built, so catching it here means the
        user is told which field is wrong instead of receiving a
        ``ValueError`` from deeper in the pipeline.

        **No truthiness guard.** ``0`` is a real value for a required ``Integer``,
        not an absent one -- Odoo treats only ``False`` and ``None`` as missing --
        so a ``if wizard.mes and ...`` test would let month ``0`` through and
        format it as ``"00"``, a code ``Tabla 01`` does not publish.
        """
        for wizard in self:
            if wizard.anio < ATS_PERIOD_YEAR_FLOOR:
                raise ValidationError(
                    self.env._(
                        "The reported year %(year)s is before %(floor)s. The SRI "
                        'catalog states the year "debe corresponder a periodos '
                        'del %(floor)s en adelante", so no ATS can be filed for '
                        "it and no catalog version is loaded for it either.",
                        year=wizard.anio,
                        floor=ATS_PERIOD_YEAR_FLOOR,
                    )
                )
            if not 1 <= wizard.mes <= 12:
                raise ValidationError(
                    self.env._(
                        "The reported month %(month)s does not exist. A period "
                        "is a calendar month, and Tabla %(table)s publishes one "
                        "code per month.",
                        month=wizard.mes,
                        table=TABLA_PERIOD,
                    )
                )

    def _l10n_ec_period(self):
        """The reported period, as the layers below speak it."""
        self.ensure_one()
        return AtsPeriod(self.anio, self.mes)

    def _l10n_ec_month_code(self):
        """The reported month as ``Tabla 01`` spells it: two digits."""
        self.ensure_one()
        return f"{self.mes:02d}"

    def _l10n_ec_reader(self):
        """A :class:`~l10n_ec_ats.validators.CatalogReader` over this env."""
        self.ensure_one()
        return CatalogReader(self.env)

    def _l10n_ec_month_entry(self):
        """The one ``Tabla 01`` row the reported month must match.

        Zero-padded, because that is how ``Tabla 01`` stores its codes and an
        unpadded lookup matches nothing -- see the module docstring. Resolved
        through :func:`~l10n_ec_ats.validators.resolve_one`, so zero entries and
        two entries are both refusals rather than a silent ``None``.
        """
        self.ensure_one()
        return resolve_one(
            self._l10n_ec_reader(),
            TABLA_PERIOD,
            self._l10n_ec_month_code(),
            self._l10n_ec_period().catalog_probe,
        )

    # ------------------------------------------------------------------
    # The air seam
    # ------------------------------------------------------------------

    def _l10n_ec_air_codes(self, period):
        """Which ``codRetAir`` codes need which ``air`` sub-report, for ``period``.

        :class:`~l10n_ec_ats.validators.AirConditionalCodes` is the seam ATS-11
        left open, and this is where it is closed from the catalog. The SRI
        publishes no column saying which code needs which sub-report and it
        cannot be derived from the concept -- ``338`` is *Compra local de banano
        a productor* in 2016 and *Producción y venta local de banano* from 2020
        -- so the grouping is **era-scoped data** on
        ``l10n.ec.ats.income.withholding.rate.detail_group``, resolved for the
        reported period like every other catalog read.

        **The model, then the filter.** ``_applicable_on`` is ``@api.model`` and
        its ``search`` discards the calling recordset, so resolving against the
        model and filtering afterwards is the only ordering that keeps the
        temporal filter. Intersecting before would discard the filter instead and
        return every era of every concept at once.

        Only the concept's **code** comes out, never a rate: the group says which
        sub-report applies, and the rate is the collector's separate read.
        """
        self.ensure_one()
        rates = self.env["l10n.ec.ats.income.withholding.rate"]._applicable_on(
            period.catalog_probe
        )

        def codes(group):
            return frozenset(
                rates.filtered(lambda rate: rate.detail_group == group).mapped(
                    "concept_id.code"
                )
            )

        return AirConditionalCodes(dividend=codes("dividend"), banana=codes("banana"))

    # ------------------------------------------------------------------
    # The preflight -- §5.6 Level 3
    # ------------------------------------------------------------------

    def _l10n_ec_preflight(self, period):
        """Resolve every catalog lookup the reported period needs.

        The lookups are grouped by what they decide, not by table number, because
        that is what a reader of a failure needs:

        * ``Tabla 12`` -- **one** VAT regime at a time. Two entries in force
          would be two regimes at once, which is why this is resolved as a whole
          table and not per code.
        * ``Tabla 11`` -- the six IVA-withholding shares that coexist, so
          "exactly one" applies per code rather than to the table.
        * ``Tabla 01`` -- the reported month's own row, so ``Mes`` is the
          catalogue's code and not a formatted number.
        * ``Tabla 02`` -- the identification types, and the RUC rows in
          particular: with no RUC row the module 11 check digit cannot be applied
          to ``IdInformante``, and a rule that silently stops applying is worse
          than one that fails.
        * ``Tabla 04`` and ``Tabla 05`` -- at least one credit-note document
          type and one tax support in force, for the same reason.

        Per-code lookups that belong to a **document** -- the tax support on a
        bill, the payment form on an invoice, a ``Tabla 3.10`` rate on an
        income withholding -- are left to the collectors, which already resolve
        each one and report it against the document that carries it. Duplicating
        them here would report the same gap twice with the document named in
        neither place.

        :return: a list of problem strings, **empty when the period is covered**.
            Never raises: the caller aggregates.
        """
        self.ensure_one()
        reader = self._l10n_ec_reader()
        day = period.catalog_probe
        checks = (
            (
                f"Tabla {TABLA_IVA_RATE}, the VAT regime in force for {period.label}",
                lambda: resolve_regime(reader, TABLA_IVA_RATE, day),
            ),
            (
                f"Tabla {TABLA_IVA_RETENTION}, the IVA withholding shares in "
                f"force for {period.label}",
                lambda: resolve_rates(reader, TABLA_IVA_RETENTION, day),
            ),
            (
                f"Tabla {TABLA_PERIOD}, the month row for {period.label}",
                self._l10n_ec_month_entry,
            ),
            (
                f"Tabla {TABLA_IDENTIFICATION_TYPE}, the RUC identification "
                f"types in force for {period.label}",
                lambda: ruc_codes(reader, day),
            ),
            (
                f"Tabla {TABLA_DOCUMENT_TYPE}, the credit-note document types "
                f"in force for {period.label}",
                lambda: credit_note_codes(reader, day),
            ),
            (
                f"Tabla {TABLA_TAX_SUPPORT}, the tax supports in force for "
                f"{period.label}",
                lambda: reader.by_table(TABLA_TAX_SUPPORT, day)
                or self._refuse(
                    TABLA_TAX_SUPPORT,
                    f"no entry covers {day}, so no tax support can be resolved",
                ),
            ),
        )
        problems = []
        for what, resolve in checks:
            problems.extend(self._l10n_ec_catalog_attempt(what, resolve))
        return problems

    def _refuse(self, table_code, detail):
        """Build a coverage refusal for a table that published nothing.

        :func:`~l10n_ec_ats.validators.resolve_one` already names the table, the
        code and the windows it found; what it cannot do is ask *"does this table
        cover the period at all?"* without a code to ask about, and naming a code
        here would be a code list this module owns. So the message is built here
        from the table number alone.
        """
        raise CatalogResolutionError(
            f"Tabla {table_code}: {detail}. No catalog version covers the "
            f"reported period, so no code from this table can be resolved for it.",
            table=table_code,
            code="",
            day=self._l10n_ec_period().catalog_probe,
            found=0,
        )

    # ------------------------------------------------------------------
    # Tabla 3.10 -- the income withholding rates the period needs
    # ------------------------------------------------------------------

    def _l10n_ec_reported_concepts(self, period):
        """The ``codRetAir`` codes the reported period's documents withhold.

        Selection only, no catalog read: the **codes** come from
        ``account.tax.l10n_ec_code_ats``, which is a capture, and the collector's
        own selection is reused so the two cannot disagree about which documents
        the period holds.

        The codes are needed *before* collection rather than after, because the
        collector leaves a document with an unresolvable rate **out** of the block
        and reports it. Reading the payload afterwards would find nothing to
        check, and the preflight would pass on exactly the period that cannot be
        filed.
        """
        self.ensure_one()
        collector = self.env["l10n.ec.ats.collector"]
        first_day, last_day = period.first_day, period.last_day
        codes = set()
        for move in collector._l10n_ec_compras_moves(
            self.company_id, first_day, last_day
        ):
            for line in collector._l10n_ec_withholding_lines(move, "purchase"):
                for tax in line.tax_ids.filtered(
                    lambda candidate: (
                        candidate.tax_group_id.l10n_ec_type
                        == "withhold_income_purchase"
                    )
                ):
                    if tax.l10n_ec_code_ats:
                        codes.add(tax.l10n_ec_code_ats)
        return codes

    def _l10n_ec_air_rate_problems(self, period):
        """Every ``Tabla 3.10`` concept the period needs, resolved or refused.

        Three ways to fail, all named with the table, the code and the window:

        * the concept is not in ``Tabla 3.10`` at all;
        * no rate -- or more than one -- is in force on the reported day;
        * the rate that does apply is flagged ``unresolved``, meaning the source
          states a range or a legal reference instead of a number.

        ``unresolved`` is the one that matters most. **1689 of the 3149 rates
        carry no percentage**, so the source states a rate far less often than it
        states a cell, and a number invented to fill one would be
        indistinguishable from a real one in the filed return.

        :return: a list of problem strings, empty when every concept resolves.
        """
        self.ensure_one()
        day = period.catalog_probe
        concept_model = self.env["l10n.ec.ats.income.withholding.concept"]
        rate_model = self.env["l10n.ec.ats.income.withholding.rate"]
        problems = []
        for code in sorted(self._l10n_ec_reported_concepts(period)):
            concept = concept_model.search([("code", "=", code)], limit=1)
            if not concept:
                problems.append(
                    self.env._(
                        "Tabla %(table)s does not define concept %(code)s, which "
                        "the reported period withholds. The tax's ATS code cannot "
                        "be resolved to a rate, so no porcentajeAir is reported "
                        "for it. Check l10n_ec_code_ats on the tax.",
                        table=TABLA_INCOME_WITHHOLDING,
                        code=code,
                    )
                )
                continue
            # The model, then the filter -- never a scoped ``search``, which would
            # discard the temporal filter and return every era at once.
            rates = rate_model._applicable_on(day).filtered(
                lambda rate, wanted=concept: rate.concept_id == wanted
            )
            if len(rates) != 1:
                problems.append(
                    self.env._(
                        "Tabla %(table)s has %(count)s rates for concept "
                        "%(code)s on %(day)s, and exactly one is required: zero "
                        "means a coverage hole and more than one means two eras "
                        "claim the same day.",
                        table=TABLA_INCOME_WITHHOLDING,
                        count=len(rates),
                        code=code,
                        day=day,
                    )
                )
                continue
            if rates.unresolved:
                problems.append(
                    self.env._(
                        "Tabla %(table)s states no single percentage for concept "
                        "%(code)s in the window %(start)s..%(end)s: %(note)s. "
                        "Guessing one would put an invented rate in a filed "
                        "return, so the period is not generated.",
                        table=TABLA_INCOME_WITHHOLDING,
                        code=code,
                        start=rates.date_start,
                        end=rates.date_end or "open",
                        note=rates.source_note or "no number in the source cell",
                    )
                )
        return problems

    @staticmethod
    def _l10n_ec_catalog_attempt(what, resolve):
        """Run one resolution, keeping its message if it refuses.

        A ``CatalogResolutionError`` is the only failure mode here, and it
        already carries the table, the code, the day and the windows it found.
        Anything else is a defect in this module rather than a data problem, so
        letting it escape keeps it from hiding behind a data error.
        """
        try:
            resolve()
        except CatalogResolutionError as error:
            return [f"{what}: {error}"]
        return []

    # ------------------------------------------------------------------
    # The payload
    # ------------------------------------------------------------------

    def _l10n_ec_payload(self, period):
        """Collect every block and assemble the payload the builder renders.

        :return: ``(payload, problems)``. ``payload`` is ``{}`` whenever
            ``problems`` is non-empty, for the same reason the collector returns
            no row when it has an error for one: a caller could not tell a zero
            from a value nobody was able to source.
        """
        self.ensure_one()
        company = self.company_id
        first_day, last_day = period.first_day, period.last_day
        collector = self.env["l10n.ec.ats.collector"]
        problems = []

        compras, compras_errors = collector.collect_compras_with_errors(
            company, first_day, last_day
        )
        ventas, ventas_errors = collector.collect_ventas_with_errors(
            company, first_day, last_day
        )
        (
            ventas_establecimiento,
            establishment_errors,
        ) = collector.collect_ventas_establecimiento_with_errors(
            company, first_day, last_day
        )
        anulados, anulados_errors = collector.collect_anulados_with_errors(
            company, first_day, last_day
        )
        header, header_errors = collector.collect_iva_header_with_errors(
            ventas, ventas_establecimiento
        )

        problems.extend(self._l10n_ec_collector_problems("compras", compras_errors))
        problems.extend(self._l10n_ec_collector_problems("ventas", ventas_errors))
        problems.extend(
            self._l10n_ec_collector_problems(
                "ventasEstablecimiento", establishment_errors
            )
        )
        problems.extend(self._l10n_ec_collector_problems("anulados", anulados_errors))
        problems.extend(self._l10n_ec_collector_problems("iva", header_errors))
        problems.extend(self._l10n_ec_preflight(period))
        # Last, because it is the one that has to run on the documents rather than
        # on the payload: the collector has already left an unresolvable document
        # out of the block by now.
        problems.extend(self._l10n_ec_air_rate_problems(period))
        if problems:
            return {}, problems
        return {
            "header": self._l10n_ec_header(period, header),
            "compras": compras,
            "ventas": ventas,
            "ventasEstablecimiento": ventas_establecimiento,
            "anulados": anulados,
        }, []

    def _l10n_ec_header(self, period, header):
        """The ``ivaType`` scalars: the wizard's own fields plus the collector's.

        Two of them -- ``numEstabRuc`` and ``totalVentas`` -- are **defined** in
        terms of the ``ventas`` and ``ventasEstablecimiento`` blocks, and are read
        out of :meth:`collect_iva_header_with_errors` rather than re-derived
        here. The ficha calls ``totalVentas`` a *casillero no editable*, and a
        second pass over the documents is precisely how a header and its own
        block would drift apart.

        ``codigoOperativo`` and ``TipoIDInformante`` are read from
        :mod:`~l10n_ec_ats.builder` rather than spelled out a third time. They
        are the only two literals §4.4 exempts, and the builder **requires** both
        to be present -- ``HEADER_ENUMERATED_VALUES`` refuses anything else
        rather than overriding it.
        """
        self.ensure_one()
        company = self.company_id
        merged = dict(header)
        merged.update(
            {
                "TipoIDInformante": TIPO_ID_INFORMANTE,
                "IdInformante": company.partner_id.vat,
                "razonSocial": self._l10n_ec_business_name(),
                "Anio": f"{period.year:04d}",
                "Mes": self._l10n_ec_month_code(),
                "codigoOperativo": CODIGO_OPERATIVO,
                "regimenMicroempresa": self._l10n_ec_regimen_microempresa(),
            }
        )
        return merged

    def _l10n_ec_business_name(self):
        """``razonSocial``, accent-stripped by the builder.

        ``razonSocialType`` is ``[a-zA-Z0-9\\s]``, so it rejects ``ñ`` and every
        accented letter. That is the builder's rule and its job -- the builder
        reduces the text once, at the one place that owns the pattern -- so the
        name is handed over as the record spells it. The company's declared
        business name wins over the partner's legal name, which is the same
        precedence ``account.edi.document`` applies when it renders
        ``razonSocial``.
        """
        self.ensure_one()
        company = self.company_id
        return company.l10n_ec_business_name or company.partner_id.name or ""

    def _l10n_ec_regimen_microempresa(self):
        """``regimenMicroempresa``, or ``False`` to emit no element.

        §5.3: derived, not assumed. Two conditions, neither of them a month list
        held in Python:

        * the company **declares** a regime -- ``l10n_ec_regimen`` is a RIMPE
          field, so a value means the taxpayer is in one;
        * the ``Tabla 01`` row of the reported month names a **semestral**
          regime, which is what the sheet's own descriptions say for the two
          semestral months and do not say for the other ten.

        The **code** is the catalogue row's, never a literal. A ``{06, 12}`` set
        would be a code list this module owns, and one that could disagree with
        the catalogue the moment the SRI republishes the table.
        """
        self.ensure_one()
        if not self.company_id.l10n_ec_regimen:
            return False
        entry = self._l10n_ec_month_entry()
        if TABLA_1_SEMESTRAL_KEYWORD not in (entry.description or "").upper():
            return False
        return entry.code

    # ------------------------------------------------------------------
    # Validation -- the second layer
    # ------------------------------------------------------------------

    def _l10n_ec_validation(self, payload, period, air_codes):
        """Apply the business rules and split the verdicts.

        :return: ``(violations, problems)``. ``problems`` carries only the
            **blocking** ones, rendered for the user; ``violations`` carries
            every finding, both severities, so a caller can report an *alerta*
            without refusing a file the SRI would accept. Flattening the two
            would either block that file or let one it refuses through.
        :rtype: tuple
        """
        self.ensure_one()
        violations = ()
        problems = []
        try:
            violations = validate_ats(
                payload,
                period,
                env=self.env,
                air_codes=air_codes,
            )
        except CatalogResolutionError as error:
            # The business layer reads the catalog too -- ``Tabla 11`` shares per
            # element, the credit-note rows, the RUC rows -- and a lookup it
            # cannot answer is a coverage hole like any other. It joins the same
            # message instead of escaping as a ValueError from four layers down.
            return (), [
                self.env._(
                    "The business rules could not read the catalog for "
                    "%(period)s: %(error)s",
                    period=period.label,
                    error=error,
                )
            ]
        problems.extend(
            self.env._(
                "%(rule)s -- %(where)s%(field)s %(message)s",
                rule=violation.rule,
                where=f"{violation.where}: " if violation.where else "",
                field=violation.field,
                message=violation.message,
            )
            for violation in blocking(violations)
        )
        return violations, problems

    def _l10n_ec_schema_problems(self, xml_string, period):
        """The grammar layer's verdict on the **rendered** document, as problems.

        It runs after the builder and not on the payload: the file the SRI
        receives is what has to satisfy ``ats.xsd``, and the two layers are not
        interchangeable -- ``establecimiento="000"`` validates here and is
        refused by the business layer, which is precisely why both exist.
        """
        self.ensure_one()
        result = validate_ats_xml(xml_string)
        if result.is_valid:
            return []
        return [
            self.env._(
                "ats.xsd rejected the document built for %(period)s: %(error)s",
                period=period.label,
                error=error,
            )
            for error in result.errors
        ]

    # ------------------------------------------------------------------
    # Packaging
    # ------------------------------------------------------------------

    def _l10n_ec_archive_stem(self, period):
        """``AT{mmaaaa}``: month then year, both zero-padded, no separator."""
        self.ensure_one()
        return f"{ATS_ARCHIVE_PREFIX}{period.month:02d}{period.year:04d}"

    def _l10n_ec_package(self, period, xml_string):
        """The archive bytes: one XML member, named after the archive.

        ``zipfile`` writes the member with its own name and no directory entry,
        so opening the result yields exactly one file. A second member -- even a
        readme -- would be something the ficha does not describe, so the archive
        holds the document and nothing else.
        """
        self.ensure_one()
        stem = self._l10n_ec_archive_stem(period)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(f"{stem}{ATS_MEMBER_SUFFIX}", xml_string.encode("utf-8"))
        return buffer.getvalue()

    def _l10n_ec_attachment(self, period, archive_bytes):
        """Attach the archive to the wizard record that produced it.

        Attached rather than handed back inline so the download goes through
        ``/web/content`` with the same access check as any other file, and so the
        bytes a user saves are the bytes that were validated rather than a round
        trip through a browser variable.
        """
        self.ensure_one()
        return self.env["ir.attachment"].create(
            {
                "name": f"{self._l10n_ec_archive_stem(period)}{ATS_ARCHIVE_SUFFIX}",
                "raw": archive_bytes,
                "mimetype": ATS_ARCHIVE_MIMETYPE,
                "res_model": self._name,
                "res_id": self.id,
            }
        )

    # ------------------------------------------------------------------
    # The pipeline
    # ------------------------------------------------------------------

    def _l10n_ec_run(self):
        """Collect, validate, build, check, package and attach -- in that order.

        The order is the argument. The business rules run **before** the builder
        because they read the payload and the builder refuses to represent
        anything malformed; ``ats.xsd`` runs **after** it because the schema
        describes the rendered document and nothing else. Nothing is packaged
        until both have passed, so an attachment never exists for a file that was
        refused.

        :return: ``(attachment, violations)``. Every violation comes back,
            blocking or not, so a caller can report what was found without
            re-running the pipeline.
        :rtype: tuple
        :raises UserError: with **every** problem found, not the first.
        """
        self.ensure_one()
        period = self._l10n_ec_period()
        air_codes = self._l10n_ec_air_codes(period)
        payload, problems = self._l10n_ec_payload(period)
        violations = ()
        xml_string = ""
        if not problems:
            violations, validation_problems = self._l10n_ec_validation(
                payload, period, air_codes
            )
            problems.extend(validation_problems)
        if not problems:
            xml_string = build_ats_xml(payload)
            problems.extend(self._l10n_ec_schema_problems(xml_string, period))
        if problems:
            raise UserError(self._l10n_ec_refusal(period, problems))
        return (
            self._l10n_ec_attachment(period, self._l10n_ec_package(period, xml_string)),
            violations,
        )

    def generate(self):
        """Build the ATS, record what was warned about, and offer the download.

        The entry point, and the whole public surface of this model. Nothing is
        returned when generation is refused: the ``UserError`` is the answer, and
        an action pointing at a file that was never built would misdescribe what
        exists.

        **The non-blocking findings are kept, not dropped.** ATS-11 splits its
        findings in two, and only one of them stops generation. Raising a
        ``UserError`` for the other would make a file the SRI accepts unfileable,
        so they cannot be exceptions; and Odoo 19 has no non-raising user-facing
        exception to raise instead -- ``odoo.exceptions`` carries no ``Warning``
        and no ``Notification``, ``from odoo.exceptions import Warning`` is what
        the mandatory ``odoo-exception-warning`` check exists to refuse, and the
        ``warning`` dict a button returns is the **onchange** contract, read in
        ``odoo.orm.models._onchange_eval`` and nowhere in the action path. So the
        warnings are written to :attr:`warnings` and the form renders them: the
        download still happens, and the person about to send the file to the SRI
        can read what the SRI may question before they do.
        """
        attachment, violations = self._l10n_ec_run()
        self.warnings = self._l10n_ec_warning_report(violations)
        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{attachment.id}?download=true",
            "target": "self",
        }

    def _l10n_ec_warning_report(self, violations):
        """The non-blocking findings, as one readable block, or ``False``.

        Every finding is listed rather than only the first, for the same reason
        the refusal aggregates: somebody reading this is about to file a return,
        and a summary that hid four findings behind the fifth would cost another
        round trip. ``False`` rather than an empty string so the field renders
        nothing at all on a clean period instead of an empty box.

        Only :func:`~l10n_ec_ats.validators.warnings_of` reaches this -- a
        blocking finding has already stopped generation before the call, so
        including one here would report a document that was never produced.
        """
        self.ensure_one()
        reported = warnings_of(violations)
        if not reported:
            return False
        lines = "\n".join(
            self.env._(
                "%(index)s. %(rule)s -- %(where)s%(field)s %(message)s",
                index=index,
                rule=violation.rule,
                where=f"{violation.where}: " if violation.where else "",
                field=violation.field,
                message=violation.message,
            )
            for index, violation in enumerate(reported, start=1)
        )
        return self.env._(
            "%(count)s finding(s) did not stop this file. They are not "
            "blocking, but the SRI may question them, so read them before "
            "filing:\n\n%(lines)s",
            count=len(reported),
            lines=lines,
        )

    def _l10n_ec_refusal(self, period, problems):
        """The one message a bad period produces.

        Every problem, numbered, under a single statement of what happened and
        what was **not** done. The last sentence is not decoration: a reader who
        fixed three documents and re-ran generation needs to know the file was
        not produced and no value was assumed, and a message listing only the
        problems would leave them wondering whether a fourth document quietly
        made it in with a placeholder.
        """
        self.ensure_one()
        numbered = "\n".join(
            f"{index}. {problem}" for index, problem in enumerate(problems, start=1)
        )
        return self.env._(
            "The ATS for %(period)s cannot be generated. %(count)s problem(s) "
            "must be resolved first, and none of them was worked around:\n\n"
            "%(problems)s\n\n"
            "No file was produced and no value was assumed. A rate, a code or a "
            "document field that cannot be resolved for the reported period is "
            "never substituted, because a substituted value is "
            "indistinguishable from a real one in a filed return.",
            period=period.label,
            count=len(problems),
            problems=numbered,
        )

    def _l10n_ec_collector_problems(self, block, errors):
        """The collectors' per-document errors, as one string each.

        The collectors return rather than raise on purpose -- one unusable
        document must not hide the other nineteen -- so this is where their
        output becomes the user's answer. Each line names the block, the ATS
        field and the record, because somebody fixing a month needs all three.
        """
        self.ensure_one()
        lines = []
        for error in errors:
            record = error.get("move") or error.get("journal")
            lines.append(
                self.env._(
                    "%(block)s / %(field)s[%(owner)s]: %(message)s",
                    block=block,
                    field=error.get("field") or "-",
                    owner=record.display_name if record else "-",
                    message=error["message"],
                )
            )
        return lines
