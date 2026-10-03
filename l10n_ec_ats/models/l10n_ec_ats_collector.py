import unicodedata

from odoo import api, models

from odoo.addons.l10n_ec.models.res_partner import (
    PartnerIdTypeEc,
    verify_final_consumer,
)

#: ``ats.xsd`` ``fechaType``: ``dd/mm/yyyy``. The schema validates the shape but
#: performs no calendar check, so this is formatting only.
ATS_DATE_FORMAT = "%d/%m/%Y"

#: The ``detalleCompras`` elements that carry an IVA withholding, paired with
#: the ``Tabla 11`` percentage each one reports.
#:
#: The right-hand side is XSD element naming, which is schema knowledge rather
#: than catalogue data: ``ats.xsd`` simply names one of its elements after the
#: rate that element carries. The left-hand side is **not** a shortcut around the
#: catalogue -- the percentage a withholding is filed under is always resolved
#: from the ``Tabla 11`` record in force on the reported period, and this mapping
#: is consulted only afterwards, to choose which element that resolved rate
#: belongs in. ``test_23_the_retention_elements_are_the_ones_tabla_11_publishes``
#: pins these keys against the percentages the catalogue actually loads, so a
#: seventh published rate fails the test instead of silently filing a row into
#: the wrong element.
IVA_RETENTION_ELEMENTS = {
    10.0: "valRetBien10",
    20.0: "valRetServ20",
    30.0: "valorRetBienes",
    50.0: "valRetServ50",
    70.0: "valorRetServicios",
    100.0: "valRetServ100",
}

#: ``account.tax.group.l10n_ec_type`` values routing a tax base into an ATS base
#: field. Localization field values, not SRI catalogue codes.
#:
#: The non-zero VAT groups are **absent on purpose**: a localization may publish
#: any number of them, so they are read from the field's own selection at call
#: time by :meth:`_l10n_ec_gravable_vat_types` instead of being listed here.
BASE_TYPES = {
    "baseNoGraIva": ("not_charged_vat",),
    "baseImponible": ("zero_vat",),
    "baseImpExe": ("exempt_vat",),
}

#: The same buckets for the ``ventas`` block, which is **narrower on purpose**.
#:
#: ``detalleVentasType`` has no ``baseImpExe`` element -- ``detalleComprasType``
#: has one and this one does not -- so an exempt sale contributes to no bucket at
#: all rather than to a bucket the schema cannot carry. Reusing :data:`BASE_TYPES`
#: verbatim would emit an element the ATS document could not hold.
VENTAS_BASE_TYPES = {
    "baseNoGraIva": ("not_charged_vat",),
    "baseImponible": ("zero_vat",),
}

#: The three ``ventas`` base buckets ``totalVentas`` is **defined** as the sum
#: of, in the order ``Catalogo_ATS.xls`` / ``ESQUEMA TIPO 1 Y 2`` row 10 names
#: them: *"debe ser igual a la sumatoria de los valores registrados en los campos
#: baseNoGraIva, Base Imponible y baseimpGrav"*.
#:
#: Held as a module constant rather than restated inside the header collector so
#: the header and ``ventasEstab`` cannot disagree about which buckets count. The
#: tax-group types behind each name are read at call time by
#: :meth:`_l10n_ec_ventas_buckets` -- ``baseImpGrav`` covers every non-zero VAT
#: group the localization may publish, which is not a list this file can own.
VENTAS_TOTAL_BASE_FIELDS = ("baseNoGraIva", "baseImponible", "baseImpGrav")

#: ``account.tax.group.l10n_ec_type`` values routing a withheld amount into a
#: ``ventas`` retention element.
#:
#: The mirror image of what the purchases collector keys on: ``valorRetIva`` is
#: what *the client* withheld from us, so it is a **sale** withholding, booked
#: against a sale-side tax group. A withholding attached to the same document on
#: the purchase side is a different thing entirely and never reaches this map.
SALE_WITHHOLDING_TYPES = {
    "valorRetIva": "withhold_vat_sale",
    "valorRetRenta": "withhold_income_sale",
}

#: ``account.journal.l10n_latam_use_documents`` mapped to the word ``Tabla 20``
#: uses in that row's description.
#:
#: These are descriptions, not codes, following
#: :data:`TABLA_14_KEYWORD_BY_COMPANY_TYPE` for the same reason: the code that
#: reaches the file is always the catalogue row's own, and the word is only how
#: that row is picked out. The ficha settles the mapping itself -- "when the
#: emission question is not activated, place emission type F" -- and a journal
#: that issues documents is one that emits electronically.
TABLA_20_KEYWORD_BY_USES_DOCUMENTS = {
    False: "FISICA",
    True: "ELECTRONICA",
}

#: The phrase ``Tabla 4`` spells its credit-note row with.
#:
#: It says in so many words that ``formaPago`` "no aplica para los tipos de
#: comprobantes Notas de Crédito (04)", so a credit-note row carries no payment
#: form. The rule belongs to a *document type*, and this is how that row is found
#: in the catalogue without this file holding the code.
TABLA_4_CREDIT_NOTE_KEYWORD = "NOTA DE CR"

#: The special consumption tax has its own amount field and its own group type.
ICE_TYPES = ("ice",)

#: ``res.partner.company_type`` values and the ``Tabla 14`` row each selects.
#:
#: ``Tabla 14`` states its two rows as ``PERSONA NATURAL`` and ``SOCIEDAD``, and
#: no Odoo field links a partner to that table, so the correspondence is spelled
#: out here against the wording the SRI publishes rather than inferred from the
#: code order. It is the weakest seam in this collector and is only reached for a
#: foreign supplier, where ``tipoProv`` is required. The **code** that reaches the
#: file still comes from the catalogue record, never from this mapping.
TABLA_14_KEYWORD_BY_COMPANY_TYPE = {
    "person": "PERSONA NATURAL",
    "company": "SOCIEDAD",
}


class L10nEcAtsCollector(models.AbstractModel):
    """Turn ``account.move`` records into ATS block payloads.

    Every method here is a **pure reader**: it searches, reads and returns
    Python values, and it never writes and never raises. That is what makes the
    collector testable on its own, and it is also what keeps the two rules this
    layer exists to enforce honest:

    * **A missing value is never substituted.** No ``'9999999999'``, no ``"02"``
      default, no ``False`` turned into ``0.00``. A field that cannot be sourced
      from a record becomes a blocking problem reported against the document and
      the field, so generation stops instead of filing an invented value. This is
      the deliberate difference from Odoo Enterprise's ``_get_purchase_values``,
      which fabricates the authorization number (§5.9.1).
    * **``000`` is never a valid establishment or emission point.** ``ats.xsd``
      accepts it -- ``establecimientoType`` and ``ptoEmisionType`` carry only a
      ``[0-9]{3}`` pattern -- while the ficha numbers establishments from ``001``
      (§5.4b). The rule is enforced here rather than left to a schema that will
      happily pass a file the SRI rejects.

    The catalogue is read through ``_applicable_on``, and every lookup must return
    **exactly one** entry. Zero is a coverage hole, more than one an overlap, and
    both are reported rather than papered over.

    An ``AbstractModel`` gets no ``ir.model`` record, so it needs no ACL. It is
    also the seam the later collectors join: ``ventas``,
    ``ventasEstablecimiento`` and ``anulados`` add their methods to this model.

    The ``ventasEstablecimiento`` block is where ``000`` finally meets the
    schema. ``establecimientoType`` and ``ptoEmisionType`` carry only a
    ``[0-9]{3}`` pattern, so ``000`` validates on ``compras`` and ``anulados``
    and this collector has to refuse it on its own. ``ventasEstabType``
    (``ats.xsd:1468``) and ``numEstabRucType`` (``ats.xsd:1482``) both carry
    ``minExclusive 000``, so the rule is enforced here **and** by the schema --
    which still does not make it optional, because ``account.journal`` accepts
    ``000`` today and would otherwise propagate it straight into the file.
    """

    _name = "l10n.ec.ats.collector"
    _description = "ATS block collectors"

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    @api.model
    def collect_compras(self, company, date_start, date_finish):
        """Return the ``compras`` rows of one period, one per document.

        A document that cannot be completed without inventing a value is **left
        out**, because emitting it would mean emitting the invention. Use
        :meth:`collect_compras_with_errors` to learn why; this entry point exists
        for callers that only need the rows it can honestly produce.

        :return: a list of dicts keyed by the ATS XML element names of
            ``detalleComprasType``, so the builder is a straight mapping with no
            renaming layer. Amounts are **absolute**: ``monedaType`` has
            ``minInclusive 0.0``, so a credit note is reduced rather than negated.
        """
        rows, _errors = self.collect_compras_with_errors(
            company, date_start, date_finish
        )
        return rows

    @api.model
    def collect_compras_with_errors(self, company, date_start, date_finish):
        """Return ``(rows, errors)`` for one period.

        Same payload as :meth:`collect_compras`, plus the blocking problems found
        on the way. Errors and values travel together rather than the collector
        raising, because one unusable document must not hide the other nineteen:
        the caller decides whether to abort (§5.6 Level 3) or to report and
        continue.

        Each error is a dict carrying the offending ``move``, the ATS ``field`` it
        belongs to, and a translated ``message`` naming the document, the field
        and -- where a catalogue is involved -- the table, the code and the
        values that would have been valid.
        """
        rows = []
        errors = []
        for move in self._l10n_ec_compras_moves(company, date_start, date_finish):
            row, move_errors = self._l10n_ec_compras_row(move, date_start)
            errors.extend(move_errors)
            if row:
                rows.append(row)
        return rows, errors

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    @api.model
    def _l10n_ec_compras_moves(self, company, date_start, date_finish):
        """Posted vendor documents of ``company`` whose accounting date is in the
        window.

        ``fechaRegistro`` is the accounting date, so it is the natural selection
        key: a document is reported in the period it was registered in. Sales
        documents, journal entries and drafts are out -- an ATS reports
        purchases, and only ones the company has actually booked.
        """
        return self.env["account.move"].search(
            [
                ("company_id", "=", company.id),
                ("move_type", "in", ("in_invoice", "in_refund")),
                ("state", "=", "posted"),
                ("date", ">=", date_start),
                ("date", "<=", date_finish),
            ],
            order="date, id",
        )

    # ------------------------------------------------------------------
    # Row assembly
    # ------------------------------------------------------------------

    @api.model
    def _l10n_ec_compras_row(self, move, period_start):
        """Build one ``detalleCompras`` payload, or explain why it cannot be.

        Every problem found is reported, not just the first, so somebody fixing a
        month of purchases sees the whole list in one pass.

        :return: ``(row, errors)``. ``row`` is ``{}`` whenever ``errors`` is
            non-empty -- a partial row is never returned, because the caller
            could not tell a zero from a value nobody was able to source.
        """
        errors = []
        partner = move.commercial_partner_id
        # The day every catalogue lookup resolves against: the reported period
        # itself. The ficha requires ``fechaRegistro`` to *equal* that period.
        reported = self._l10n_ec_reported_date(move, period_start, errors)

        def report(field, message):
            errors.append({"move": move, "field": field, "message": message})

        row = {
            "codSustento": self._l10n_ec_cod_sustento(move, reported, report),
            "tpIdProv": self._l10n_ec_tp_id_prov(partner, reported, report),
            "idProv": self._l10n_ec_id_prov(partner, report),
            "tipoComprobante": self._l10n_ec_tipo_comprobante(move, reported, report),
            "parteRel": self._l10n_ec_parte_rel(partner),
            "fechaRegistro": self._l10n_ec_fecha(move.date),
            "establecimiento": False,
            "puntoEmision": False,
            "secuencial": False,
            "fechaEmision": self._l10n_ec_fecha_emision(move, report),
            "autorizacion": self._l10n_ec_autorizacion(move, report),
        }
        row.update(self._l10n_ec_conditional_province(partner, reported, report))
        row.update(self._l10n_ec_document_triple(move, report))

        row.update(self._l10n_ec_compras_amounts(move))

        retentions, retention_errors = self._l10n_ec_iva_withholdings(move, reported)
        errors.extend(retention_errors)
        row.update(retentions)

        air, air_errors = self._l10n_ec_income_withholdings(move, reported)
        errors.extend(air_errors)
        if air:
            # ``air`` is ``minOccurs="0"``: no withholding means no element,
            # never an empty one.
            row["air"] = air

        payments, payment_errors = self._l10n_ec_formas_de_pago(move, reported)
        errors.extend(payment_errors)
        if payments:
            row["formasDePago"] = payments

        return (row if not errors else {}), errors

    # ------------------------------------------------------------------
    # Catalogue resolution seam
    # ------------------------------------------------------------------

    @api.model
    def _l10n_ec_applicable_entries(self, table_code, when):
        """Every entry of one referential table in force on ``when``.

        The table filter is applied with ``filtered`` rather than by chaining a
        second ``search`` onto the result. ``BaseModel.search`` is ``@api.model``,
        so calling it on a recordset ignores that recordset and searches the whole
        model -- which would silently throw away the temporal filter and hand back
        every entry of every era, making the window look like no window at all.
        """
        table = self.env["l10n.ec.ats.catalog.table"].search(
            [("code", "=", table_code)], limit=1
        )
        if not table:
            return self.env["l10n.ec.ats.catalog.entry"]
        applicable = self.env["l10n.ec.ats.catalog.entry"]._applicable_on(when)
        return applicable.filtered(lambda entry: entry.table_id == table)

    @api.model
    def _l10n_ec_resolve_entry(self, table_code, code, when, ats_field, report):
        """The single entry of ``table_code`` for ``code`` in force on ``when``.

        Returns an empty recordset after reporting unless exactly one entry
        applies. This is the one choke point every catalogue read goes through,
        which is what makes "no hardcoded values" enforceable rather than
        aspirational: there is no code path here that could fall back to a
        literal.
        """
        applicable = self._l10n_ec_applicable_entries(table_code, when)
        entries = applicable.filtered(
            lambda entry, wanted=code: self._l10n_ec_same_code(entry.code, wanted)
        )
        if len(entries) == 1:
            return entries
        report(
            ats_field,
            self.env._(
                "Tabla %(table)s has %(count)s entries for code %(code)s on "
                "%(when)s; exactly one is required. Codes in force that day: "
                "%(valid)s.",
                table=table_code,
                count=len(entries),
                code=code,
                when=self._l10n_ec_fecha(when),
                valid=", ".join(sorted(applicable.mapped("code"))) or "-",
            ),
        )
        return self.env["l10n.ec.ats.catalog.entry"]

    @api.model
    def _l10n_ec_same_code(self, left, right):
        """Whether two SRI codes denote the same catalogue row.

        The two sides do not always agree on padding:
        ``l10n_latam.document.type`` codes the SRI's *Factura* ``01`` while
        ``Tabla 4`` stores it as ``1``, so a plain string comparison would reject
        every valid document. Only leading zeros are forgiven: they are padding,
        not meaning.
        """
        if left == right:
            return True
        bare_left = (left or "").lstrip("0")
        return bool(bare_left) and bare_left == (right or "").lstrip("0")

    @api.model
    def _l10n_ec_reported_date(self, move, period_start, errors):
        """The day the catalogue is resolved against: the reported period.

        The ficha requires ``fechaRegistro`` to equal the period being reported,
        not merely to fall inside the search window. A caller that hands over a
        window wider than a month -- a range export, or a mistake -- is told so,
        rather than being allowed to file a February document inside a January
        report.
        """
        accounting_date = move.date
        if not accounting_date:
            errors.append(
                {
                    "move": move,
                    "field": "fechaRegistro",
                    "message": self.env._(
                        "%(move)s cannot be reported in the ATS: fechaRegistro is "
                        "not set. Set the accounting date on the document.",
                        move=move.display_name,
                    ),
                }
            )
            return period_start
        if (accounting_date.year, accounting_date.month) != (
            period_start.year,
            period_start.month,
        ):
            errors.append(
                {
                    "move": move,
                    "field": "fechaRegistro",
                    "message": self.env._(
                        "%(move)s cannot be reported in the ATS: fechaRegistro "
                        "%(date)s falls outside the reported period %(month)s. "
                        "An ATS covers one month, and fechaRegistro must equal "
                        "it.",
                        move=move.display_name,
                        date=self._l10n_ec_fecha(accounting_date),
                        month=self._l10n_ec_fecha(period_start),
                    ),
                }
            )
        return period_start

    # ------------------------------------------------------------------
    # Primary key
    # ------------------------------------------------------------------

    @api.model
    def _l10n_ec_cod_sustento(self, move, reported, report):
        """``codSustento``, validated against ``Tabla 5`` for the period.

        ``account.move.l10n_ec_tax_support`` is a capture, not a list: it is a
        ``Char`` precisely so that a code this addon has never heard of can still
        be recorded. Validating it here is what makes that safe -- the rejection
        message names the codes the catalogue does accept, read from the records,
        so the guidance cannot go stale the way a dropdown does.
        """
        code = move.l10n_ec_tax_support
        if not code:
            report(
                "codSustento",
                self.env._(
                    "%(move)s cannot be reported in the ATS: no tax support is "
                    "captured. Tabla 5 requires exactly one code per document, "
                    "and ATS does not guess it.",
                    move=move.display_name,
                ),
            )
            return False
        self._l10n_ec_resolve_entry("05", code, reported, "codSustento", report)
        return code

    @api.model
    def _l10n_ec_tipo_comprobante(self, move, reported, report):
        """``tipoComprobante``, cross-checked against ``Tabla 4`` and against the
        document types the chosen ``Tabla 5`` row covers.

        The ficha requires the document type to be one the chosen tax support
        allows, and both sides of that cross-reference are stored on the records:
        ``Tabla 4`` keeps the support codes and ``Tabla 5`` keeps the document
        type codes.
        """
        document_type = move.l10n_latam_document_type_id
        code = document_type.code
        if not code:
            report(
                "tipoComprobante",
                self.env._(
                    "%(move)s cannot be reported in the ATS: the document type "
                    "is not set. Tabla 4 requires one.",
                    move=move.display_name,
                ),
            )
            return False
        self._l10n_ec_resolve_entry("04", code, reported, "tipoComprobante", report)
        support = self._l10n_ec_applicable_entries("05", reported).filtered(
            lambda entry, wanted=move.l10n_ec_tax_support: entry.code == wanted
        )
        allowed = support.document_type_codes if support else ""
        if allowed and not any(
            self._l10n_ec_same_code(token.strip(), code) for token in allowed.split(",")
        ):
            report(
                "tipoComprobante",
                self.env._(
                    "%(move)s cannot be reported in the ATS: document type "
                    "%(code)s (%(name)s) is not one tax support %(support)s "
                    "covers. Tabla 5 allows: %(allowed)s.",
                    move=move.display_name,
                    code=code,
                    name=document_type.display_name,
                    support=move.l10n_ec_tax_support or "-",
                    allowed=allowed,
                ),
            )
        return code

    @api.model
    def _l10n_ec_tp_id_prov(self, partner, reported, report):
        """``tpIdProv``, resolved through ``Tabla 2`` for the period.

        Which purchase-side identification code applies follows from the
        supplier's identification, and core ``l10n_ec`` already knows that
        mapping -- ``PartnerIdTypeEc.get_ats_code_for_partner`` is what its own
        EDI documents use, so this collector does not decide it. The catalogue's
        job is to confirm the code is a real ``Tabla 2`` row on that day, and that
        the row points at a transaction type that exists.
        """
        vat = partner.vat
        if verify_final_consumer(vat):
            # The Consumer Final sentinel. ``Tabla 2`` does carry a row for it,
            # but on the sales side, so a purchase against it cannot be filed.
            report(
                "tpIdProv",
                self.env._(
                    "%(partner)s is identified as %(vat)s, which is Consumer "
                    "Final. The SRI files no purchase against that "
                    "identification; bill the real supplier.",
                    partner=partner.display_name,
                    vat=vat,
                ),
            )
            return False
        if not vat:
            report(
                "tpIdProv",
                self.env._(
                    "%(partner)s has no identification number, so it cannot be "
                    "reported as a supplier.",
                    partner=partner.display_name,
                ),
            )
            return False
        code = PartnerIdTypeEc.get_ats_code_for_partner(partner, "in_invoice")
        if code is None:
            report(
                "tpIdProv",
                self.env._(
                    "%(partner)s uses an identification type the ATS does not "
                    "describe, so tpIdProv cannot be derived from it.",
                    partner=partner.display_name,
                ),
            )
            return False
        entry = self._l10n_ec_resolve_entry(
            "02", code.value, reported, "tpIdProv", report
        )
        if entry and not self._l10n_ec_transaction_type_resolves(entry, reported):
            report(
                "tpIdProv",
                self.env._(
                    "Tabla 2 entry %(code)s points at transaction type "
                    "%(types)s, which Tabla A does not define on %(when)s.",
                    code=entry.code,
                    types=entry.transaction_type_codes or "-",
                    when=self._l10n_ec_fecha(reported),
                ),
            )
            return False
        return entry.code if entry else code.value

    @api.model
    def _l10n_ec_transaction_type_resolves(self, entry, reported):
        """Whether ``entry``'s transaction-type cross-reference resolves.

        ``Tabla 2`` names the referred tables' transaction type in its own
        column, and ``Tabla A`` is the registry of those. A dangling reference
        means the catalog does not actually describe this row, which is a
        coverage problem worth reporting rather than ignoring.
        """
        types = [
            token.strip()
            for token in (entry.transaction_type_codes or "").split(",")
            if token.strip()
        ]
        if not types:
            # FONDOS Y FIDEICOMISOS and COMPROBANTES ANULADOS name no row of the
            # referred tables, so an empty cross-reference is a fact, not a hole.
            return True
        applicable = self._l10n_ec_applicable_entries("A", reported)
        return all(
            applicable.filtered(lambda entry, wanted=code: entry.code == wanted)
            for code in types
        )

    @api.model
    def _l10n_ec_id_prov(self, partner, report, *, field="idProv", subject=None):
        """``idProv`` / ``idCliente``: the identification, placeholders rejected.

        The ficha names the sentinels for an exterior identification: they are not
        an identification of anybody. Consumer Final is handled where it has to be
        refused anyway -- :meth:`_l10n_ec_tp_id_prov` on the purchase side, and
        deliberately *not* on the sales side, where it is a real client type; what
        remains here is the all-zero placeholder.

        ``field`` and ``subject`` are the only things that differ between the two
        blocks, so the check itself lives here once. An empty identification
        reports nothing: :meth:`_l10n_ec_tp_id_prov` and
        :meth:`_l10n_ec_tp_id_cliente` have already named the missing
        identification by the time this runs.
        """
        vat = (partner.vat or "").strip()
        if not vat:
            return False
        if set(vat) == {"0"}:
            report(
                field,
                self.env._(
                    "%(vat)s is not a real identification number, so "
                    "%(partner)s cannot be reported as %(subject)s.",
                    vat=vat,
                    partner=partner.display_name,
                    subject=subject or self.env._("a supplier"),
                ),
            )
            return False
        return vat

    @api.model
    def _l10n_ec_parte_rel(self, partner):
        """``parteRel``: the user asserts it, the collector only reads it.

        The ficha is explicit that this is a choice rather than a derivation --
        the taxpayer selects SI or NO and an error is raised when neither is
        chosen -- so the flag is a deliberate assertion and unchecked means ``NO``.
        """
        return "SI" if partner.l10n_ec_related_party else "NO"

    @api.model
    def _l10n_ec_conditional_province(self, partner, reported, report):
        """``tipoProv`` and ``denoProv``, only for a foreign supplier.

        Both are conditional on ``tpIdProv`` being the exterior-identification
        code, which is exactly what ``PartnerIdTypeEc`` returns the
        passport member for. Neither is emitted for a local supplier: an absent
        key means an absent element, never an empty one.
        """
        if (
            PartnerIdTypeEc.get_ats_code_for_partner(partner, "in_invoice")
            != PartnerIdTypeEc.IN_PASSPORT
        ):
            return {}
        values = {}
        tipo_prov = self._l10n_ec_tabla_14_entry(partner, reported)
        if tipo_prov:
            values["tipoProv"] = tipo_prov.code
        else:
            report(
                "tipoProv",
                self.env._(
                    "%(partner)s is identified from abroad, so the ATS requires "
                    "tipoProv. Tabla 14 states no row matching a %(nature)s "
                    "supplier on %(when)s.",
                    partner=partner.display_name,
                    nature=partner.company_type,
                    when=self._l10n_ec_fecha(reported),
                ),
            )
        if partner.name:
            # ``denoProvType`` is ``[a-zA-Z0-9\\s]``: an accented supplier name is
            # rejected by the schema, so what cannot be carried is dropped here
            # rather than mangled into something the record never said.
            values["denoProv"] = self._l10n_ec_strip_accents(partner.name)
        return values

    @api.model
    def _l10n_ec_description_contains(self, entry, keyword):
        """Whether ``entry``'s catalogue description names ``keyword``.

        A catalogue description is prose the SRI spells with accents -- *Facturación
        Física*, *Ley Solidaridad -Zonas Afectadas* -- and a keyword is not, so
        both sides are reduced to their ASCII letters before comparing, the
        keyword case-insensitively. Only the comparison is affected: the code that
        reaches the file is the row's own, accents and all.
        """
        plain = "".join(
            character
            for character in unicodedata.normalize("NFKD", entry.description or "")
            if character.isascii() and (character.isalnum() or character.isspace())
        )
        return keyword in plain.upper()

    @api.model
    def _l10n_ec_tabla_14_entry(self, partner, reported):
        """The ``Tabla 14`` row matching the partner's nature, or an empty set."""
        keyword = TABLA_14_KEYWORD_BY_COMPANY_TYPE.get(partner.company_type)
        if not keyword:
            return self.env["l10n.ec.ats.catalog.entry"]
        return self._l10n_ec_applicable_entries("14", reported).filtered(
            lambda entry: self._l10n_ec_description_contains(entry, keyword)
        )[:1]

    # ------------------------------------------------------------------
    # Document identity
    # ------------------------------------------------------------------

    @api.model
    def _l10n_ec_document_triple(self, move, report):
        """``establecimiento``, ``puntoEmision`` and ``secuencial``: the
        **supplier's**, from the document number recorded on the bill.

        ATS files the vendor's establishment, not ours. The triple is typed on the
        bill because nothing parses a vendor's XML yet (§5.8).

        The access key is the documented recovery path when the number is
        missing: ``l10n_ec_generate_access_key`` lays a key out as
        ``ddmmyyyy(8) + codDoc(2) + ruc(13) + ambiente(1) + entity(3) +
        ptoEmi(3) + secuencial(9) + codNumerico(8) + emision(1) + verificador(1)``
        = 49 characters, so the supplier's triple occupies ``[24:39]``.

        ``000`` is refused on both three-digit halves. The XSD accepts it; the
        ficha does not (§5.4b), and a file the SRI rejects is worse than a
        refusal to generate one.
        """
        triple = self._l10n_ec_triple_from_document_number(move)
        if not triple:
            triple = self._l10n_ec_triple_from_access_key(move)
        if not triple:
            report(
                "establecimiento",
                self.env._(
                    "%(move)s cannot be reported in the ATS: the supplier's "
                    "document number is not set and its access key does not "
                    "carry one either. Record the number on the bill as "
                    "ESTABLISHMENT-POINT-SEQUENTIAL.",
                    move=move.display_name,
                ),
            )
            return {}
        entity, point, sequence = triple
        values = {"secuencial": sequence}
        for field, value in (
            ("establecimiento", entity),
            ("puntoEmision", point),
        ):
            if set(value) == {"0"}:
                report(
                    field,
                    self.env._(
                        "%(move)s cannot be reported in the ATS: %(field)s is "
                        "%(value)s. The SRI numbers establishments and emission "
                        "points from 001; 000 is never valid, even though "
                        "ats.xsd accepts it.",
                        move=move.display_name,
                        field=field,
                        value=value,
                    ),
                )
            else:
                values[field] = value
        return values

    @api.model
    def _l10n_ec_triple_from_document_number(self, move):
        """Split the recorded ``EST-PTO-SECUENCIAL`` number, or return ``False``.

        ``_l10n_ec_split_document_number`` is the addon's own splitter and pads
        each half the way the ficha requires, so it is reused rather than
        reimplemented -- one place decides what a well-formed number looks like.
        """
        document_number = move.l10n_latam_document_number
        if not document_number:
            return False
        parts = document_number.split("-")
        if len(parts) != 3 or not all(part.strip() for part in parts):
            return False
        try:
            entity, point, sequence = self.env[
                "account.edi.document"
            ]._l10n_ec_split_document_number(document_number)
        except (ValueError, AttributeError):
            return False
        return entity, point, sequence

    @api.model
    def _l10n_ec_triple_from_access_key(self, move):
        """The supplier's triple carved out of the access key, or ``False``.

        A 49-digit key, because that is the length the generator produces; a
        shorter or non-numeric value is not a key and is not guessed at. Used only
        as a recovery path: the recorded document number is the primary source.
        """
        access_key = move.l10n_ec_xml_access_key or ""
        if len(access_key) != 49 or not access_key.isdigit():
            return False
        return access_key[24:27], access_key[27:30], access_key[30:39]

    @api.model
    def _l10n_ec_autorizacion(self, move, report):
        """``autorizacion``: the supplier's SRI authorization number.

        The ficha requires it and ``autorizacionType`` accepts 3 to 49 digits.
        Odoo Enterprise fills ``'9999999999'`` here, because "the government
        software does not allow to report documents without authorization
        number"; ATS refuses instead (§5.9.1), since a fabricated authorization in
        a filed return is worse than a missing file. §5.8 explains why this is
        often empty in practice: nothing parses a vendor's XML yet.
        """
        authorization = (move.l10n_ec_authorization_number or "").strip()
        if not authorization:
            report(
                "autorizacion",
                self.env._(
                    "%(move)s cannot be reported in the ATS: the supplier's "
                    "authorization number is not set. ATS will not invent one. "
                    "Record it on the bill, or leave the document out of the "
                    "period until it is known.",
                    move=move.display_name,
                ),
            )
            return False
        return authorization

    @api.model
    def _l10n_ec_fecha_emision(self, move, report):
        """``fechaEmision``: the vendor's emission date.

        The ficha requires it to be at or before ``fechaRegistro`` and no more
        than a year before it. Both are checked here rather than deferred,
        because a row that cannot be filed is not worth emitting.
        """
        emission = move.invoice_date
        if not emission:
            report(
                "fechaEmision",
                self.env._(
                    "%(move)s cannot be reported in the ATS: the supplier's "
                    "emission date is not set.",
                    move=move.display_name,
                ),
            )
            return False
        if move.date:
            if emission > move.date:
                report(
                    "fechaEmision",
                    self.env._(
                        "%(move)s cannot be reported in the ATS: fechaEmision "
                        "%(emission)s is after fechaRegistro %(registration)s.",
                        move=move.display_name,
                        emission=self._l10n_ec_fecha(emission),
                        registration=self._l10n_ec_fecha(move.date),
                    ),
                )
            elif (move.date - emission).days > 365:
                report(
                    "fechaEmision",
                    self.env._(
                        "%(move)s cannot be reported in the ATS: fechaEmision "
                        "%(emission)s is more than a year before fechaRegistro "
                        "%(registration)s.",
                        move=move.display_name,
                        emission=self._l10n_ec_fecha(emission),
                        registration=self._l10n_ec_fecha(move.date),
                    ),
                )
        return self._l10n_ec_fecha(emission)

    # ------------------------------------------------------------------
    # Amounts
    # ------------------------------------------------------------------

    @api.model
    def _l10n_ec_gravable_vat_types(self):
        """The non-zero VAT tax-group types, read from the localization itself.

        ``account.tax.group.l10n_ec_type`` publishes one value per rate the
        localization supports, so the gravable set cannot be listed in Python
        without going stale the first time a rate is added. Reading them from the
        field's own selection is why this is a method and not a constant -- and
        why ``zero_vat``, ``not_charged_vat`` and ``exempt_vat`` fall outside the
        match rather than being excluded from it one by one.
        """
        selection = self.env["account.tax.group"]._fields["l10n_ec_type"].selection
        return tuple(code for code, _label in selection if code.startswith("vat"))

    @api.model
    def _l10n_ec_compras_amounts(self, move):
        """The four base buckets and the two tax amounts.

        A base belongs to exactly one bucket, so the split follows the tax group
        on each line rather than being guessed from amounts: ``not_charged_vat``
        is not subject to VAT, ``zero_vat`` is taxed at zero, the ``vat*`` groups
        are taxed above zero, ``exempt_vat`` is exempt, and ``ice`` is the special
        consumption tax reported on its own.

        Every value is absolute. ``monedaType`` has ``minInclusive 0.0`` and the
        schema has no per-line negative, so a credit note is reported as
        magnitudes (§5.4).

        Only ``display_type`` product lines carry a base, and
        ``_prepare_edi_tax_details`` already filters on exactly that, so section
        and note lines cannot leak into a bucket.
        """
        gravable = self._l10n_ec_gravable_vat_types()
        buckets = dict(BASE_TYPES)
        buckets["baseImpGrav"] = gravable
        values = {
            field: self._l10n_ec_taxed_amount(move, types, "base_amount")
            for field, types in buckets.items()
        }
        values["montoIva"] = self._l10n_ec_taxed_amount(move, gravable, "tax_amount")
        values["montoIce"] = self._l10n_ec_taxed_amount(move, ICE_TYPES, "tax_amount")
        return values

    @api.model
    def _l10n_ec_taxed_amount(self, move, types, key):
        """Sum one of the aggregated tax totals over the lines taxed by
        ``types``.

        The filter is applied inside ``_prepare_edi_tax_details``, which splits a
        line's base per tax, so a line carrying taxes from two groups contributes
        only the share belonging to the group being asked for.
        """

        def keep(base_line, tax_data):
            if not tax_data:
                return True
            return tax_data["tax"].tax_group_id.l10n_ec_type in types

        return abs(move._prepare_edi_tax_details(filter_to_apply=keep)[key])

    # ------------------------------------------------------------------
    # Withholdings
    # ------------------------------------------------------------------

    @api.model
    def _l10n_ec_withholding_lines(self, move, withholding_type):
        """The withholding basis lines booked against ``move``.

        ``l10n_ec_invoice_withhold_id`` is the only link a withholding carries
        back to the document it supports, so the collector follows it rather than
        guessing from dates or partners. Draft withholdings are ignored: a
        withholding the company has not filed does not reduce the purchase or
        the sale.

        ``withholding_type`` is required rather than defaulted. A company can
        hold both a purchase and a sale withholding against a document, and they
        are different events with different ATS elements, so which one is wanted
        is never a matter of taste: ``compras`` reads ``purchase``, ``ventas``
        reads ``sale``.
        """
        withholdings = move.l10n_ec_withhold_ids.filtered(
            lambda withhold: (
                withhold.state == "posted"
                and withhold.l10n_ec_withholding_type == withholding_type
            )
        )
        return withholdings.line_ids.filtered(
            lambda line: (
                line.display_type == "product"
                and line.l10n_ec_invoice_withhold_id == move
                and line.tax_ids
            )
        )

    @api.model
    def _l10n_ec_iva_withholdings(self, move, reported):
        """The six ``Tabla 11`` elements, bucketed by the rate the tax carries.

        A VAT-withholding tax *is* its rate, and ``Tabla 11`` publishes exactly
        the six rates the schema has an element for. So the rate is read from the
        tax and then confirmed against the catalogue: exactly one ``Tabla 11``
        entry must be in force with that percentage on the reported day. That
        check is the point -- it turns a tax row into a *verified* rate rather
        than an assumed one, and a rate the SRI never published is reported
        instead of filed.

        All six elements are emitted, defaulting to zero, because the ficha marks
        all six obligatory even though ``ats.xsd`` makes three optional. Zero is a
        real, sourced amount here: the catalogue published no withholding at that
        rate, so there is nothing to withhold.
        """
        values = {element: 0.0 for element in IVA_RETENTION_ELEMENTS.values()}
        errors = []
        applicable = self._l10n_ec_applicable_entries("11", reported)
        for line in self._l10n_ec_withholding_lines(move, "purchase"):
            for tax in line.tax_ids.filtered(
                lambda candidate: (
                    candidate.tax_group_id.l10n_ec_type == "withhold_vat_purchase"
                )
            ):
                rate = abs(tax.amount)
                entries = applicable.filtered(
                    lambda entry, wanted=rate: float(entry.percentage) == wanted
                )
                if len(entries) != 1:
                    errors.append(
                        {
                            "move": move,
                            "field": "valRetIva",
                            "message": self.env._(
                                "%(move)s withholds VAT at %(rate)s%%, but "
                                "Tabla 11 has %(count)s such rates in force on "
                                "%(when)s. Exactly one is required; ATS will "
                                "not guess which element the amount belongs in.",
                                move=move.display_name,
                                rate=rate,
                                count=len(entries),
                                when=self._l10n_ec_fecha(reported),
                            ),
                        }
                    )
                    continue
                element = IVA_RETENTION_ELEMENTS.get(float(entries.percentage))
                if not element:
                    errors.append(
                        {
                            "move": move,
                            "field": "valRetIva",
                            "message": self.env._(
                                "Tabla 11 publishes a %(rate)s%% IVA "
                                "withholding rate on %(when)s and ats.xsd has "
                                "no compras element for it. The SRI schema "
                                "would have to gain one before this could be "
                                "filed.",
                                rate=entries.percentage,
                                when=self._l10n_ec_fecha(reported),
                            ),
                        }
                    )
                    continue
                values[element] += abs(line.l10n_ec_withhold_tax_amount)
        return values, errors

    @api.model
    def _l10n_ec_income_withholdings(self, move, reported):
        """The ``air`` block: one entry per income-withholding basis line.

        ``air`` is a single element (``maxOccurs="1"``) holding unbounded
        ``detalleAir``, so a document with several concepts carries them all in
        one row instead of repeating the document.

        The concept is ``account.tax.l10n_ec_code_ats`` on the **tax**, not on
        the tax group: every withholding group shares a generic ``"1"``/``"2"``
        ``l10n_ec_xml_fe_code`` and it says nothing about which concept was
        withheld (§5.3).

        The rate is resolved from ``Tabla 3.10`` for the reported period, and an
        unresolved rate is reported rather than completed. That matters more here
        than anywhere else: the source states no single number for most of its
        rate cells, and a rate invented to fill one would be indistinguishable
        from a real one in the filed file.
        """
        entries = []
        errors = []
        for line in self._l10n_ec_withholding_lines(move, "purchase"):
            for tax in line.tax_ids.filtered(
                lambda candidate: (
                    candidate.tax_group_id.l10n_ec_type == "withhold_income_purchase"
                )
            ):
                rate = self._l10n_ec_air_rate(move, tax, reported, errors)
                if not rate:
                    continue
                entries.append(
                    {
                        "codRetAir": tax.l10n_ec_code_ats,
                        "baseImpAir": abs(line.balance),
                        "porcentajeAir": rate.percentage,
                        "valRetAir": abs(line.l10n_ec_withhold_tax_amount),
                    }
                )
        return entries, errors

    @api.model
    def _l10n_ec_air_rate(self, move, tax, reported, errors):
        """The ``Tabla 3.10`` rate of a withheld concept, or ``None``.

        Three ways to fail, all reported and none papered over:

        * the concept is not in ``Tabla 3.10`` at all;
        * no rate -- or more than one -- is in force on the reported day;
        * the rate that does apply is flagged ``unresolved``, meaning the source
          states a range or a legal reference instead of a number.
        """
        code = tax.l10n_ec_code_ats
        Concept = self.env["l10n.ec.ats.income.withholding.concept"]
        concept = Concept.search([("code", "=", code or "")])
        if not concept:
            errors.append(
                {
                    "move": move,
                    "field": "codRetAir",
                    "message": self.env._(
                        "%(move)s withholds income tax under code %(code)s, "
                        "which Tabla 3.10 does not define. The tax's ATS code "
                        "cannot be resolved to a rate, so no porcentajeAir is "
                        "reported for it. Check l10n_ec_code_ats on the tax.",
                        move=move.display_name,
                        code=code or "-",
                    ),
                }
            )
            return None
        # ``filtered``, not a chained ``search``: see
        # :meth:`_l10n_ec_applicable_entries` for why that would discard the
        # temporal filter.
        rates = (
            self.env["l10n.ec.ats.income.withholding.rate"]
            ._applicable_on(reported)
            .filtered(lambda rate: rate.concept_id == concept)
        )
        if len(rates) != 1:
            errors.append(
                {
                    "move": move,
                    "field": "porcentajeAir",
                    "message": self.env._(
                        "Tabla 3.10 has %(count)s rates for concept %(code)s on "
                        "%(when)s; exactly one is required.",
                        count=len(rates),
                        code=concept.code,
                        when=self._l10n_ec_fecha(reported),
                    ),
                }
            )
            return None
        if rates.unresolved:
            errors.append(
                {
                    "move": move,
                    "field": "porcentajeAir",
                    "message": self.env._(
                        "Tabla 3.10 states no single percentage for concept "
                        "%(code)s on %(when)s: %(note)s. Guessing one would put "
                        "an invented rate in a filed return, so the document is "
                        "not reported.",
                        code=concept.code,
                        when=self._l10n_ec_fecha(reported),
                        note=rates.source_note or "no number in the source cell",
                    ),
                }
            )
            return None
        return rates

    # ------------------------------------------------------------------
    # Payment form
    # ------------------------------------------------------------------

    @api.model
    def _l10n_ec_formas_de_pago(self, move, reported):
        """``formasDePago``, resolved through ``Tabla 13`` for the period.

        The element wraps unbounded ``formaPago`` and is ``minOccurs="0"``: the
        ficha makes it conditional on the transaction crossing a threshold, which
        is a business rule for the validator layer to apply. So an absent payment
        method means an absent element rather than an empty one, and a form
        ``Tabla 13`` does not publish on that day is reported.
        """
        payment = move.l10n_ec_sri_payment_id
        if not payment.code:
            return [], []
        applicable = self._l10n_ec_applicable_entries("13", reported)
        entries = applicable.filtered(
            lambda entry: self._l10n_ec_same_code(entry.code, payment.code)
        )
        if len(entries) != 1:
            return [], [
                {
                    "move": move,
                    "field": "formasDePago",
                    "message": self.env._(
                        "%(move)s states payment form %(code)s, which Tabla 13 "
                        "does not publish on %(when)s. Codes in force that day: "
                        "%(valid)s.",
                        move=move.display_name,
                        code=payment.code,
                        when=self._l10n_ec_fecha(reported),
                        valid=", ".join(sorted(applicable.mapped("code"))) or "-",
                    ),
                }
            ]
        return [{"formaPago": entries.code}], []

    # ------------------------------------------------------------------
    # Ventas -- the aggregated block
    # ------------------------------------------------------------------

    @api.model
    def collect_ventas(self, company, date_start, date_finish):
        """Return the ``ventas`` rows of one period, aggregated.

        One row per ``(tpIdCliente, idCliente, tipoComprobante, tipoEmision)``,
        not per document: ``numeroComprobantes`` carries the count and the bases
        and taxes are the totals of every document folded into it. Two invoices
        to the same client under the same document type are one row with a count
        of two.

        A group that cannot be completed without inventing a value is **left
        out** as a whole, because a partially summed row would describe a set of
        documents the company never had. Use :meth:`collect_ventas_with_errors`
        to learn why.

        :return: a list of dicts keyed by the ATS XML element names of
            ``detalleVentasType``, so the builder is a straight mapping with no
            renaming layer. Amounts are **absolute**: ``monedaType`` has
            ``minInclusive 0.0``, so a credit note is reduced rather than negated
            and is filed under its own ``tipoComprobante``.
        """
        rows, _errors = self.collect_ventas_with_errors(
            company, date_start, date_finish
        )
        return rows

    @api.model
    def collect_ventas_with_errors(self, company, date_start, date_finish):
        """Return ``(rows, errors)`` for one period.

        Same two-layer shape as :meth:`collect_compras_with_errors`, and for the
        same reason: one unusable document must not hide the other nineteen, so
        the caller decides whether to abort (§5.6 Level 3) or to report and
        continue. An error names the document it belongs to, which for an
        aggregated row is the member that could not be filed rather than the
        whole group.
        """
        rows = []
        errors = []
        for moves in self._l10n_ec_ventas_groups(company, date_start, date_finish):
            row, group_errors = self._l10n_ec_ventas_row(moves, date_start)
            errors.extend(group_errors)
            if row:
                rows.append(row)
        return rows, errors

    # ------------------------------------------------------------------
    # Selection and grouping
    # ------------------------------------------------------------------

    @api.model
    def _l10n_ec_ventas_moves(self, company, date_start, date_finish):
        """Posted customer documents of ``company`` whose accounting date is in
        the window.

        ``out_refund`` is included and is not a special case: a credit note is
        filed under its own document type, so it arrives here as an ordinary
        document and is grouped like one.
        """
        return self.env["account.move"].search(
            [
                ("company_id", "=", company.id),
                ("move_type", "in", ("out_invoice", "out_refund")),
                ("state", "=", "posted"),
                ("date", ">=", date_start),
                ("date", "<=", date_finish),
            ],
            order="date, id",
        )

    @api.model
    def _l10n_ec_ventas_groups(self, company, date_start, date_finish):
        """The documents of the period, folded into their rows.

        Insertion order follows ``_l10n_ec_ventas_moves``, so the rows come out in
        the order the documents were booked rather than in an arbitrary one.
        """
        groups = {}
        for move in self._l10n_ec_ventas_moves(company, date_start, date_finish):
            groups.setdefault(self._l10n_ec_ventas_group_key(move), []).append(move)
        return list(groups.values())

    @api.model
    def _l10n_ec_ventas_group_key(self, move):
        """The tuple one ``detalleVentas`` row is aggregated by.

        ``CLAVE PRIMARIA (2)`` marks exactly three general key components for this
        block: ``tpIdCliente``, ``idCliente`` and ``tipoComprobante``.
        ``tipoEmision`` is **not** among them -- the sheet does not list the field
        at all, neither as a key component nor otherwise -- which would leave the
        question of what happens to two documents that differ only in emission
        type unanswered.

        The ficha answers it: "se puede ingresar el mismo tipo de documento
        siempre que difiera de la emisión de un mismo cliente en el período
        informado" -- the same document type may be filed again for the same
        client in the same period **provided the emission type differs**. That is
        only satisfiable if a differing emission type produces a row of its own,
        so the key is the sheet's three plus ``tipoEmision``.

        Folding them instead would put a value in the file that is true of one
        document out of two, or of neither, while ``numeroComprobantes`` claimed
        both. That is the substitution this collector exists to refuse.

        Keyed on the values that reach the file rather than on the partner
        record, so two client records carrying one identification aggregate into
        one row instead of producing two rows with the same primary key.
        """
        return (
            PartnerIdTypeEc.get_ats_code_for_partner(
                move.commercial_partner_id, "out_invoice"
            ),
            (move.commercial_partner_id.vat or "").strip(),
            move.l10n_latam_document_type_id.code,
            bool(move.journal_id.l10n_latam_use_documents),
        )

    # ------------------------------------------------------------------
    # Row assembly
    # ------------------------------------------------------------------

    @api.model
    def _l10n_ec_ventas_row(self, moves, period_start):
        """Build one aggregated ``detalleVentas`` payload, or explain why not.

        :return: ``(row, errors)``. ``row`` is ``{}`` whenever ``errors`` is
            non-empty, and a single unusable member withholds the whole group:
            the bases and taxes are sums, and a sum over a subset is not a number
            the company ever had.
        """
        errors = []
        representative = moves[0]
        partner = representative.commercial_partner_id

        def reporter(move):
            """Report against ``move``, naming the document a problem belongs to.

            For a group that is not the same thing as naming the group: a member
            that cannot be filed is reported against itself, so whoever fixes the
            month sees which document is at fault rather than a list of rows.
            """

            def report(field, message):
                errors.append({"move": move, "field": field, "message": message})

            return report

        report = reporter(representative)

        reported = period_start
        for move in moves:
            reported = self._l10n_ec_reported_date(move, period_start, errors)

        # ``tpIdCliente`` and ``tipoComprobante`` are resolved for **every**
        # member, so a document that cannot be filed is named on its own rather
        # than hidden behind the one that happened to sort first.
        tp_id_cliente = False
        tipo_comprobante = False
        for move in moves:
            tp_id_cliente = self._l10n_ec_tp_id_cliente(
                move.commercial_partner_id, reported, reporter(move)
            )
            tipo_comprobante = self._l10n_ec_tipo_comprobante_ventas(
                move, reported, reporter(move)
            )

        row = {
            "tpIdCliente": tp_id_cliente,
            "idCliente": self._l10n_ec_id_cliente(partner, report),
            "tipoComprobante": tipo_comprobante,
            "tipoEmision": self._l10n_ec_tipo_emision(representative, reported, report),
            "numeroComprobantes": len(moves),
        }
        # The ficha displays ``parteRel`` only for the three identification types
        # a person or company can hold, and the consumer sentinel is not one of
        # them. ``ats.xsd`` makes the element optional, so omitting it is both
        # what the schema expects and what the ficha asks for.
        if tp_id_cliente != PartnerIdTypeEc.FINAL_CONSUMER.value:
            row["parteRelVtas"] = self._l10n_ec_parte_rel(partner)
        row.update(self._l10n_ec_conditional_client(partner, reported, report))
        row.update(self._l10n_ec_ventas_amounts(moves))

        retentions, retention_errors = self._l10n_ec_ventas_retentions(moves, reported)
        errors.extend(retention_errors)
        row.update(retentions)

        payments, payment_errors = self._l10n_ec_ventas_formas_de_pago(moves, reported)
        errors.extend(payment_errors)
        if payments and not self._l10n_ec_is_credit_note(tipo_comprobante, reported):
            row["formasDePago"] = payments

        # ``compensaciones`` is deliberately absent. It is condicional and its
        # type comes from ``Tabla 21``, but nothing in Odoo records an IVA
        # compensation under the solidarity law or on electronic money, so there
        # is no record to read it from and the key is omitted rather than filled
        # with a default. ``Tabla 21`` is loaded and available for the model that
        # will carry it.
        return (row if not errors else {}), errors

    @api.model
    def _l10n_ec_tp_id_cliente(self, partner, reported, report):
        """``tpIdCliente``, resolved through ``Tabla 2`` for the period.

        Which sale-side identification applies follows from the client's
        identification, and core ``l10n_ec`` already knows that mapping --
        ``PartnerIdTypeEc.get_ats_code_for_partner`` is what its own EDI documents
        use -- so this collector does not decide it. The catalogue's job is to
        confirm the code is a real ``Tabla 2`` row on that day and that the row
        points at a transaction type that exists.

        The final-consumer sentinel is **accepted** here, the opposite of the
        purchase rule in :meth:`_l10n_ec_tp_id_prov`: ``Tabla 2`` publishes it as
        a sale identification and the ficha's ``idCliente`` validation names
        *Consumidor Final* as one of the values the field may hold. Refusing it
        would make the most ordinary Ecuadorian sale impossible to file.
        """
        if not partner.vat:
            report(
                "tpIdCliente",
                self.env._(
                    "%(partner)s has no identification number, so it cannot be "
                    "reported as a client.",
                    partner=partner.display_name,
                ),
            )
            return False
        code = PartnerIdTypeEc.get_ats_code_for_partner(partner, "out_invoice")
        if code is None:
            report(
                "tpIdCliente",
                self.env._(
                    "%(partner)s uses an identification type the ATS does not "
                    "describe, so tpIdCliente cannot be derived from it.",
                    partner=partner.display_name,
                ),
            )
            return False
        entry = self._l10n_ec_resolve_entry(
            "02", code.value, reported, "tpIdCliente", report
        )
        if entry and not self._l10n_ec_transaction_type_resolves(entry, reported):
            report(
                "tpIdCliente",
                self.env._(
                    "Tabla 2 entry %(code)s points at transaction type "
                    "%(types)s, which Tabla A does not define on %(when)s.",
                    code=entry.code,
                    types=entry.transaction_type_codes or "-",
                    when=self._l10n_ec_fecha(reported),
                ),
            )
            return False
        return entry.code if entry else code.value

    @api.model
    def _l10n_ec_id_cliente(self, partner, report):
        """``idCliente``: the client's identification.

        The all-zero placeholder is rejected by the shared check; the consumer
        sentinel is not, and the reasoning is in :meth:`_l10n_ec_tp_id_cliente`.
        """
        return self._l10n_ec_id_prov(
            partner, report, field="idCliente", subject=self.env._("a client")
        )

    @api.model
    def _l10n_ec_tipo_comprobante_ventas(self, move, reported, report):
        """``tipoComprobante``, validated against ``Tabla 4`` for the period.

        Unlike the purchase side there is no ``codSustento`` to cross-check, and
        the ficha's own filter for this field -- *Tabla 4* filtered by *Código
        Secuencial Transacción* equal to ``04``, ``05``, ``06``, ``07`` and
        ``19``, which are the codes ``Tabla 2`` publishes as sale identifications
        -- **cannot be evaluated from the loaded catalogue**: ``Tabla 4`` stores
        two different columns for those two ideas, and the cross-check ATS-06
        performs on the purchase side already uses one of them for ``Tabla 5``.
        What is asserted here is therefore the part the catalogue can answer: that
        the code is a real ``Tabla 4`` row in force on the reported day. The
        filter is recorded for ATS-11 rather than approximated with a list of
        codes this file would then own.
        """
        document_type = move.l10n_latam_document_type_id
        code = document_type.code
        if not code:
            report(
                "tipoComprobante",
                self.env._(
                    "%(move)s cannot be reported in the ATS: the document type "
                    "is not set. Tabla 4 requires one.",
                    move=move.display_name,
                ),
            )
            return False
        self._l10n_ec_resolve_entry("04", code, reported, "tipoComprobante", report)
        return code

    @api.model
    def _l10n_ec_tipo_emision(self, move, reported, report):
        """``tipoEmision``, resolved through ``Tabla 20`` for the period.

        The signal is a record, not a flag invented here: the issuing journal's
        own ``l10n_latam_use_documents`` -- the field core ``l10n_ec`` computes
        ``l10n_ec_require_emission`` from. A journal that issues documents files
        electronically; one that does not files physically, which is the same
        answer the ficha gives for "when the emission question is not activated,
        place emission type F".

        The keyword only *selects* the ``Tabla 20`` row; the code that reaches the
        file is that row's own.
        """
        journal = move.journal_id
        uses_documents = bool(journal.l10n_latam_use_documents)
        keyword = TABLA_20_KEYWORD_BY_USES_DOCUMENTS[uses_documents]
        applicable = self._l10n_ec_applicable_entries("20", reported)
        entries = applicable.filtered(
            lambda entry: self._l10n_ec_description_contains(entry, keyword)
        )
        if len(entries) != 1:
            report(
                "tipoEmision",
                self.env._(
                    "%(move)s cannot be reported in the ATS: Tabla 20 has "
                    "%(count)s rows in force on %(when)s for journal "
                    "%(journal)s, which %(uses)s. Exactly one is required, and "
                    "ATS will not guess the emission type. Codes in force that "
                    "day: %(valid)s.",
                    move=move.display_name,
                    count=len(entries),
                    when=self._l10n_ec_fecha(reported),
                    journal=journal.display_name,
                    uses=(
                        self.env._("uses documents")
                        if uses_documents
                        else self.env._("does not use documents")
                    ),
                    valid=", ".join(sorted(applicable.mapped("code"))) or "-",
                ),
            )
            return False
        return entries.code

    @api.model
    def _l10n_ec_conditional_client(self, partner, reported, report):
        """``tipoCliente`` and ``denoCli``, only for a client identified by
        passport.

        The ficha displays both only when ``tpIdCliente`` is the exterior
        identification, which is exactly what ``PartnerIdTypeEc`` returns for the
        passport member -- the same condition under which the purchase side
        displays ``tipoProv`` and ``denoProv``. Neither is emitted otherwise: an
        absent key means an absent element, never an empty one.
        """
        if (
            PartnerIdTypeEc.get_ats_code_for_partner(partner, "out_invoice")
            != PartnerIdTypeEc.OUT_PASSPORT
        ):
            return {}
        values = {}
        tipo_cliente = self._l10n_ec_tabla_14_entry(partner, reported)
        if tipo_cliente:
            values["tipoCliente"] = tipo_cliente.code
        else:
            report(
                "tipoCliente",
                self.env._(
                    "%(partner)s is identified from abroad, so the ATS requires "
                    "tipoCliente. Tabla 14 states no row matching a %(nature)s "
                    "client on %(when)s.",
                    partner=partner.display_name,
                    nature=partner.company_type,
                    when=self._l10n_ec_fecha(reported),
                ),
            )
        if partner.name:
            # ``denoCliType`` is ``[a-zA-Z0-9\\s]``, as ``denoProvType`` is.
            values["denoCli"] = self._l10n_ec_strip_accents(partner.name)
        return values

    # ------------------------------------------------------------------
    # Ventas amounts
    # ------------------------------------------------------------------

    @api.model
    def _l10n_ec_ventas_amounts(self, moves):
        """The three base buckets and the two tax amounts, summed over the group.

        A base belongs to exactly one bucket and the split follows the tax group
        on each line, read exactly as on the purchase side. What differs is the
        aggregation -- one sum across every document in the row -- and the
        buckets themselves: :data:`VENTAS_BASE_TYPES` has no exempt base because
        ``detalleVentasType`` has no element for one.

        Every value is absolute. ``monedaType`` has ``minInclusive 0.0`` and the
        schema has no per-line negative, so a credit note is reported as
        magnitudes under its own document type (§5.4).

        ``montoIce`` is emitted even though ``ats.xsd`` makes it optional: the
        ficha marks it obligatorio and spells the zero case out ("when the ICE
        amount is zero, register 0.00"). A sum over no ICE lines really is zero,
        so nothing is invented by emitting it -- and the schema being more
        permissive than the norm is exactly the gap §5.4 exists for.
        """
        buckets = self._l10n_ec_ventas_buckets()
        values = {
            field: sum(
                self._l10n_ec_taxed_amount(move, types, "base_amount") for move in moves
            )
            for field, types in buckets.items()
        }
        values["montoIva"] = sum(
            self._l10n_ec_taxed_amount(
                move, self._l10n_ec_gravable_vat_types(), "tax_amount"
            )
            for move in moves
        )
        values["montoIce"] = sum(
            self._l10n_ec_taxed_amount(move, ICE_TYPES, "tax_amount") for move in moves
        )
        return values

    @api.model
    def _l10n_ec_ventas_buckets(self):
        """The three ``totalVentas`` base buckets, name to tax-group types.

        One definition, shared by :meth:`_l10n_ec_ventas_amounts` and
        :meth:`_l10n_ec_ventas_estab_amount`, because ``totalVentas`` and
        ``ventasEstab`` are only comparable if both are built from the same three
        buckets -- ``ESQUEMA`` row 10 names them for the header and row 103 for
        the block, and neither row lists a fourth.

        ``baseImpGrav`` is completed from the localization's own selection rather
        than a literal: the SRI does not name the VAT groups, it names the
        resulting rate, and this collector does not resolve rates. See
        :meth:`_l10n_ec_gravable_vat_types`.
        """
        buckets = dict(VENTAS_BASE_TYPES)
        buckets["baseImpGrav"] = self._l10n_ec_gravable_vat_types()
        return buckets

    @api.model
    def _l10n_ec_ventas_retentions(self, moves, reported):
        """``valorRetIva`` and ``valorRetRenta``: what the **client** withheld.

        Only withholdings issued on the **sale** side are read, and only the
        sale-side tax groups, so the mirror-image purchase withholding a company
        may hold against the same document is never added in. The two sides are
        different events with different ATS elements; ``valorRetIva`` says what
        the client took off us, not what we took off a supplier.

        The purchase block splits its VAT withholding across six ``Tabla 11``
        elements because it reports per document. This block carries a single
        ``valorRetIva`` because the client withholds one amount against the whole
        group. The rate each tax carries is still checked against ``Tabla 11`` for
        the reported day -- a rate the SRI never published is reported, not filed
        -- but there is no element left to choose.

        ``valorRetRenta`` resolves no ``Tabla 3.10`` rate, and deliberately so:
        unlike ``air``, this block has no per-concept breakdown, so there is
        nowhere to put a code or a percentage and an unresolved rate cannot affect
        the total that is all the schema can express here.
        """
        values = dict.fromkeys(SALE_WITHHOLDING_TYPES, 0.0)
        errors = []
        published = self._l10n_ec_applicable_entries("11", reported)
        for move in moves:
            for line in self._l10n_ec_withholding_lines(move, "sale"):
                for tax, field in self._l10n_ec_sale_withholding_taxes(line.tax_ids):
                    if field == "valorRetIva" and not self._l10n_ec_tabla_11_rate(
                        tax, published, move, reported, errors
                    ):
                        continue
                    values[field] += abs(line.l10n_ec_withhold_tax_amount)
        return values, errors

    @api.model
    def _l10n_ec_sale_withholding_taxes(self, taxes):
        """Pair each sale-side withholding tax with the element it feeds.

        A tax group that belongs to neither side is not a retention this block
        reports, and is skipped rather than reported: a purchase-side group on a
        withholding linked to a sale is a data mistake somewhere, but it is not
        this row's business to invent a reading for it.
        """
        return [
            (tax, field)
            for tax in taxes
            for field, group_type in SALE_WITHHOLDING_TYPES.items()
            if tax.tax_group_id.l10n_ec_type == group_type
        ]

    @api.model
    def _l10n_ec_tabla_11_rate(self, tax, published, move, reported, errors):
        """Whether ``tax``'s rate is a rate ``Tabla 11`` publishes on that day.

        A VAT-withholding tax *is* its rate, so the check turns a tax row into a
        **verified** rate rather than an assumed one. Exactly one ``Tabla 11``
        entry must carry that percentage on the reported day; zero is a coverage
        hole and more than one an overlap, and both are reported.
        """
        rate = abs(tax.amount)
        entries = published.filtered(lambda entry: float(entry.percentage) == rate)
        if len(entries) == 1:
            return True
        errors.append(
            {
                "move": move,
                "field": "valorRetIva",
                "message": self.env._(
                    "%(move)s withholds VAT at %(rate)s%%, but Tabla 11 has "
                    "%(count)s such rates in force on %(when)s. Exactly one is "
                    "required; ATS will not file a retention under a rate the "
                    "SRI never published.",
                    move=move.display_name,
                    rate=rate,
                    count=len(entries),
                    when=self._l10n_ec_fecha(reported),
                ),
            }
        )
        return False

    @api.model
    def _l10n_ec_ventas_formas_de_pago(self, moves, reported):
        """``formasDePago``: every payment form the group's transactions used.

        The payment form belongs to a **transaction**, not to a client, so it is
        not part of the aggregation key and not constant across a group. The ficha
        settles what to do with that: "when a single transaction used more than
        one payment form, all of the payment forms used must be reported", and
        ``formaPago`` is unbounded. So the row carries the distinct forms of every
        document folded into it, in booking order.

        Each document's own form is still resolved through ``Tabla 13`` for the
        reported day by the shared helper, so a form the SRI does not publish that
        month is reported against the document that stated it.
        """
        payments = []
        seen = set()
        errors = []
        for move in moves:
            move_payments, move_errors = self._l10n_ec_formas_de_pago(move, reported)
            errors.extend(move_errors)
            for payment in move_payments:
                if payment["formaPago"] not in seen:
                    seen.add(payment["formaPago"])
                    payments.append(payment)
        return payments, errors

    @api.model
    def _l10n_ec_is_credit_note(self, tipo_comprobante, reported):
        """Whether ``tipo_comprobante`` names a credit note, per ``Tabla 4``.

        The catalogue states that ``formaPago`` does not apply to a credit note,
        so a credit-note row carries no payment form. The row is found in
        ``Tabla 4`` by the phrase the SRI itself uses rather than by a code this
        file would have to own, and ``ats.xsd`` makes the element optional either
        way -- so the block-specific business rule and the grammar agree.
        """
        credit_notes = self._l10n_ec_applicable_entries("04", reported).filtered(
            lambda entry: self._l10n_ec_description_contains(
                entry, TABLA_4_CREDIT_NOTE_KEYWORD
            )
        )
        return bool(
            credit_notes.filtered(
                lambda entry, wanted=tipo_comprobante: self._l10n_ec_same_code(
                    entry.code, wanted
                )
            )
        )

    # ------------------------------------------------------------------
    # Ventas establecimiento -- one row per our own establishment
    # ------------------------------------------------------------------

    @api.model
    def collect_ventas_establecimiento(self, company, date_start, date_finish):
        """Return the ``ventasEstablecimiento`` rows of one period.

        One row per ``codEstab``, which ``CLAVE PRIMARIA (2)`` row 94 marks as
        this block's only general key component. Not per document and not per
        client: the ficha ties the row count to a header field instead -- *"debe
        generarse igual número de registros que el valor informado en el campo
        número de establecimientos del sujeto pasivo, inscritos en el RUC"* --
        so the row set is the taxpayer's **active RUC establishments**, not the
        ones that happened to sell. An establishment with no sales is a row at
        ``0.00``; omitting it would make ``len(rows) != numEstabRuc``, which is
        the check the ficha states.

        An establishment whose code may never be filed -- ``000`` -- is **left
        out** and reported, because emitting it would mean emitting the
        prohibition. Use :meth:`collect_ventas_establecimiento_with_errors` to
        learn why.

        :return: a list of dicts keyed by the ATS XML element names of
            ``ventaEstType``: ``codEstab`` and ``ventasEstab``. ``ivaComp`` is
            deliberately absent -- see :meth:`_l10n_ec_ventas_estab_row`.
        """
        rows, _errors = self.collect_ventas_establecimiento_with_errors(
            company, date_start, date_finish
        )
        return rows

    @api.model
    def collect_ventas_establecimiento_with_errors(
        self, company, date_start, date_finish
    ):
        """Return ``(rows, errors)`` for one period.

        Same two-layer shape as the sibling blocks, and for the same reason: one
        unusable document must not hide the rest of the month, so the caller
        decides whether to abort (§5.6 Level 3) or to report and continue.

        **One extension to the error dict.** The ATS-06 and ATS-07 blocks report
        every problem against a ``move``, so their errors carry ``{"move",
        "field", "message"}``. A bad ``l10n_ec_entity`` belongs to a **journal**
        and to no document at all, so these errors always carry ``journal`` as
        well and set ``move`` to ``False``. Every key is present on every error
        from every block, so a consumer can read either without a ``KeyError``.
        """
        errors = []
        moves = self._l10n_ec_ventas_moves(company, date_start, date_finish)
        codes = self._l10n_ec_establishment_codes(company, moves, errors)
        grouped = self._l10n_ec_group_moves_by_establishment(moves, codes)
        rows = []
        for code in codes:
            row, row_errors = self._l10n_ec_ventas_estab_row(
                code, grouped.get(code, self.env["account.move"]), date_start
            )
            errors.extend(row_errors)
            if row:
                rows.append(row)
        return rows, errors

    # ------------------------------------------------------------------
    # Establishment derivation
    # ------------------------------------------------------------------

    @api.model
    def _l10n_ec_company_journals(self, company):
        """The company's active journals, the record-backed establishment set.

        There is no ``res.establishment`` in ``l10n-ecuador`` nor in core
        ``l10n_ec``; the nearest thing that exists is the journal pair
        ``l10n_ec_entity`` / ``l10n_ec_emission`` on ``account.journal``. So the
        *ours* side of the ATS establishment composite reads ``l10n_ec_entity``
        here, and the supplier's side is read per document in
        :meth:`_l10n_ec_document_triple`.

        **Active** only. The ficha counts *"establecimientos en estado
        activo"*, so a deactivated journal's establishment is not one this
        period reports.
        """
        return self.env["account.journal"].search(
            [("company_id", "=", company.id), ("active", "=", True)],
            order="id",
        )

    @api.model
    def _l10n_ec_establishment_codes(self, company, moves, errors):
        """Every establishment of ours that may be filed this period, sorted.

        §5.2's compound derivation: the distinct ``l10n_ec_entity`` over the
        company's active journals, **unioned** with the entity segment of
        ``l10n_latam_document_number`` on the sales documents of the period.

        The union is not belt-and-braces. Changing a journal's entity after a
        document was issued leaves the establishment that document was really
        filed under with no journal declaring it any more, and reading only the
        journals would drop a real establishment from the ``numEstabRuc`` count.
        The recorded document number is the more authoritative of the two -- it
        is what the SRI received -- so where the two disagree about which
        documents belong to an establishment, the document number wins
        (:meth:`_l10n_ec_group_moves_by_establishment`).

        **The union is restricted to sales documents we issued.** A vendor bill
        carries a ``l10n_latam_document_number`` too, but that number is the
        *supplier's* triple (§5.8); reading it here would file our establishments
        with the identifiers of other people's.

        ``sale_withhold_ec`` is seeded with an **empty** entity and emission
        (``l10n_ec_withhold/data/template/account.journal-ec.csv``) and is an
        active journal of every EC company, so an empty value is skipped rather
        than emitted: ``ventasEstabType`` is ``\\d{3}`` and a blank code would be
        rejected by the schema as well as being meaningless.

        Sorted rather than kept in discovery order because a *set* of
        establishments has no natural order the way a list of documents has, and
        a sorted code list is the deterministic one that reads the same on every
        run.

        :return: the codes to report, plus the ``000`` codes found on the way,
            appended to ``errors`` and excluded from the result.
        """
        codes = set()
        for journal in self._l10n_ec_company_journals(company):
            self._l10n_ec_add_establishment(
                journal.l10n_ec_entity, codes, errors, journal=journal
            )
        for move in moves:
            triple = self._l10n_ec_triple_from_document_number(move)
            if triple:
                self._l10n_ec_add_establishment(triple[0], codes, errors, move=move)
        return sorted(codes)

    @api.model
    def _l10n_ec_add_establishment(self, code, codes, errors, move=None, journal=None):
        """Add ``code`` to ``codes``, or report why it may not be filed.

        ``000`` is refused here and nowhere else in this block, so the rule has
        exactly one seam. This is where §5.4b stops being theoretical: unlike
        ``compras`` and ``anulados``, whose carriers the schema leaves
        unconstrained, ``ventasEstabType`` (``ats.xsd:1468``) **does** carry
        ``minExclusive 000`` -- so a file carrying one breaks the schema too.

        It still has to be caught here, because nothing upstream stops it being
        written: ``account.journal._constrains_l10n_ec_entity_emission``
        (``l10n_ec_base/models/account_journal.py:18``) checks only
        ``len(value) < 3`` and ``not value.isnumeric()``, and ``"000"`` satisfies
        both.
        """
        if not code:
            # The seeded ``sale_withhold_ec`` case: an active journal with no
            # establishment at all. Not a reportable defect -- a company with no
            # establishment to file is simply not an error here.
            return
        if set(code) == {"0"}:
            errors.append(
                {
                    "move": move,
                    "journal": journal,
                    "field": "codEstab",
                    "message": self.env._(
                        "%(subject)s cannot be reported in the ATS: its "
                        "establishment is %(code)s. The SRI numbers "
                        "establishments from 001, and numEstabRuc and "
                        "codEstab both carry minExclusive 000 in ats.xsd, so "
                        "%(code)s is never valid in either place.",
                        subject=journal.display_name if journal else move.display_name,
                        code=code,
                    ),
                }
            )
            return
        codes.add(code)

    @api.model
    def _l10n_ec_group_moves_by_establishment(self, moves, codes):
        """Fold the period's sales documents into their establishment's row.

        Keyed on the establishment the **recorded document number** names, not
        on the issuing journal's current ``l10n_ec_entity``. A move whose
        establishment has already been rejected is filed under no establishment
        at all rather than being forced into a neighbouring row, which is what
        keeps a rejected code from inflating a valid row's total.
        """
        grouped = {code: self.env["account.move"] for code in codes}
        for move in moves:
            triple = self._l10n_ec_triple_from_document_number(move)
            code = triple[0] if triple else False
            if code in grouped:
                grouped[code] |= move
        return grouped

    # ------------------------------------------------------------------
    # Establishment row assembly
    # ------------------------------------------------------------------

    @api.model
    def _l10n_ec_ventas_estab_row(self, code, moves, period_start):
        """Build one ``ventaEst`` payload, or explain why it cannot be.

        :return: ``(row, errors)``. ``row`` is ``{}`` whenever ``errors`` is
            non-empty: a total over a subset of the establishment's documents is
            a figure the company never had, so a single unusable document
            withholds the whole row.
        """
        errors = []
        for move in moves:
            self._l10n_ec_reported_date(move, period_start, errors)

        def report(field, message):
            errors.append(
                {
                    "move": moves[0] if moves else False,
                    "journal": False,
                    "field": field,
                    "message": message,
                }
            )

        for move in moves:
            # The same ``Tabla 4`` guard the ``ventas`` block applies. A
            # document the SRI never published for this period cannot sit inside
            # a total that is filed as this period's sales.
            self._l10n_ec_tipo_comprobante_ventas(move, period_start, report)
        total = self._l10n_ec_ventas_estab_amount(moves)
        if errors:
            return {}, errors
        # ``ivaComp`` is deliberately absent, exactly as ``compensaciones`` is on
        # the ``ventas`` block. ``Tabla 21`` *is* loaded and in scope -- the
        # omission is a decision about a missing **source**, not a missing table:
        # nothing in Odoo records an IVA compensation under the solidarity law or
        # on electronic money, so there is nothing to read it from. The ESQUEMA
        # note says "si no existe valor colocar 0.00", but a ``0.00`` here would
        # assert that no compensation happened, which is a claim about a fact
        # this collector cannot see -- and ``ats.xsd:1465`` makes the element
        # ``minOccurs="0"``, so omitting it is also what the schema expects.
        # ``test_20`` pins the omission against the loaded catalog, so if a
        # compensation ever becomes a record the test fails and the decision is
        # taken again on purpose.
        return {"codEstab": code, "ventasEstab": total}, errors

    @api.model
    def _l10n_ec_ventas_estab_amount(self, moves):
        """The **net** sales total of one establishment over ``moves``.

        Signed, and that is the whole point of this block. ``ESQUEMA`` row 103
        requires the sum of the ``ventasEstab`` boxes to equal *"el valor neto
        (se restan los valores de NC) de todas las ventas registradas"* -- the
        **net** value, credit notes subtracted, *"caso contrario error"*. The
        ficha's own ceiling agrees and is only informative under that reading:
        *"la sumatoria del total de ventas por los establecimientos no puede ser
        mayor al valor registrado en el campo total ventas"* states a ``<=``
        against ``totalVentas``, which is only ever a real constraint when a row
        can come out below it.

        ``ats.xsd`` agrees too, and that is the clincher rather than a
        coincidence: ``ventasEstab`` is typed ``totalVentasType``
        (``ats.xsd:1464``), the **only** amount type in the whole schema whose
        pattern admits a leading minus, while every ``ventas`` base is
        ``monedaType`` with ``minInclusive 0.0``. The SRI gave this one element
        the one type that can express a reversal, and gave it to no other.

        So ``totalVentas`` -- gross, per ``ESQUEMA`` row 10 -- comes out **at or
        above** this figure, and the two are equal exactly when the period holds
        no credit note. A negative result is real: a company that credited more
        than it invoiced from one establishment has a negative net figure, and
        clamping it to ``0.00`` would state a number the company never had.

        The same three buckets ``totalVentas`` sums, read through
        :meth:`_l10n_ec_ventas_buckets`, and the **sign comes from the document
        type** -- ``out_refund`` subtracts. That is the only place the reversal
        lives: ``monedaType`` forbids a negative anywhere in ``detalleVentasType``,
        so the ``ventas`` block can only carry a credit note as its own row.
        """
        total = 0.0
        for move in moves:
            sign = -1.0 if move.move_type == "out_refund" else 1.0
            for types in self._l10n_ec_ventas_buckets().values():
                total += sign * self._l10n_ec_taxed_amount(move, types, "base_amount")
        return total

    # ------------------------------------------------------------------
    # The iva header -- numEstabRuc and totalVentas
    # ------------------------------------------------------------------

    @api.model
    def collect_iva_header(self, ventas_rows, ventas_establecimiento_rows):
        """Return the ``ivaType`` header fields both blocks feed.

        ``numEstabRuc`` and ``totalVentas`` are **header** fields, not members of
        the ``ventasEstablecimiento`` block, and each is defined in terms of a
        block:

        * ``numEstabRuc`` is the count of establishments, which is
          ``len(ventas_establecimiento_rows)`` -- the ficha requires one row per
          registered establishment, so the count *is* the row count.
        * ``totalVentas`` is the sum of ``baseNoGraIva`` + ``baseImponible`` +
          ``baseImpGrav`` over the ``ventas`` rows (``ESQUEMA`` row 10), so it
          is read out of ``ventas_rows`` rather than re-derived from the
          documents.

        **Both blocks are therefore required arguments**, and that is the point
        of the signature: the relationship between the header and the blocks is
        the whole content of these two fields, so a caller cannot obtain one
        without the other and cannot wire them to different periods by accident.
        ``totalVentas`` is emphatically *not* re-aggregated here -- the ficha
        calls it *"casillero no editable"*, and a second pass over the documents
        is precisely how a header and its own block would drift apart.

        Returns ``{}`` when the header cannot be completed. Use
        :meth:`collect_iva_header_with_errors` to learn why.
        """
        header, _errors = self.collect_iva_header_with_errors(
            ventas_rows, ventas_establecimiento_rows
        )
        return header

    @api.model
    def collect_iva_header_with_errors(self, ventas_rows, ventas_establecimiento_rows):
        """Return ``(header, errors)``, the errors being header-level.

        A header field that cannot be sourced blocks **the header**, not the
        blocks: the rows are still correct and still reportable, and whoever
        fixes the month should see them. The errors carry ``move`` and
        ``journal`` as ``False`` because a header field belongs to neither.
        """
        errors = []
        count = len(ventas_establecimiento_rows)
        num_estab_ruc = self._l10n_ec_num_estab_ruc(count)
        if not num_estab_ruc:
            errors.append(
                {
                    "move": False,
                    "journal": False,
                    "field": "numEstabRuc",
                    "message": self.env._(
                        "numEstabRuc cannot be reported: no establishment could "
                        "be filed for this period, and the ficha requires it to "
                        "be greater than 000 -- the count of establishments "
                        "registered in the RUC, which is never zero. Check the "
                        "ventasEstablecimiento block: an establishment whose "
                        "l10n_ec_entity is 000, or a sales document that cannot "
                        "be filed, would empty it."
                    ),
                }
            )
        if errors:
            return {}, errors
        return {
            "numEstabRuc": num_estab_ruc,
            "totalVentas": self._l10n_ec_total_ventas(ventas_rows),
        }, errors

    @api.model
    def _l10n_ec_num_estab_ruc(self, count):
        """``numEstabRuc``: the establishment count, zero-padded to three digits.

        ``numEstabRucType`` (``ats.xsd:1482``) is ``\\d{3}`` with
        ``minExclusive 000``, so seven establishments are ``"007"`` and never
        ``"7"``, and a count of **zero** has no valid representation at all.
        ``False`` is returned for that case rather than ``"000"``: the ficha says
        the field *"debe ser mayor a 000"*, the schema forbids ``000``, and the
        only honest answer for an empty establishment set is that there is none
        to report.
        """
        if not count:
            return False
        return str(count).zfill(3)

    @api.model
    def _l10n_ec_total_ventas(self, ventas_rows):
        """``totalVentas``: the sum of the three base buckets over ``ventas_rows``.

        ``ESQUEMA`` row 10, verbatim: *"Casillero no editable, debe ser igual a
        la sumatoria de los valores registrados en los campos baseNoGraIva,
        Base Imponible y baseimpGrav"*, and the ficha states the same three
        fields in prose. Every amount involved is a ``monedaType``, so this total
        is **gross**: a credit note contributes its magnitude exactly as its
        invoice does, and the document type is what tells the SRI the difference.

        Which is why it is **not** the same figure as the sum of
        ``ventasEstab``, and why the two are only equal in a period with no
        credit note. ``ESQUEMA`` row 103 defines the block figure as the net
        value, so the gap between them is twice the credit notes' bases -- which
        is the margin the ficha's *"no puede ser mayor"* allows, not a defect.

        A missing bucket reads as zero rather than raising: the ``ventas`` rows
        are what :meth:`_l10n_ec_ventas_amounts` produced, and it always emits
        all three, so an absent key means a caller handed over rows this
        collector did not build. Reading it as zero would be a substitution, so
        it is not done silently -- see ``test_06``, which pins that the rows the
        caller supplies are the ones that are summed.
        """
        return sum(
            sum(row.get(field) or 0.0 for field in VENTAS_TOTAL_BASE_FIELDS)
            for row in ventas_rows
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @api.model
    def _l10n_ec_fecha(self, value):
        """Format a date the way ``ats.xsd`` ``fechaType`` reads it."""
        return value.strftime(ATS_DATE_FORMAT) if value else False

    @api.model
    def _l10n_ec_strip_accents(self, text):
        """Reduce ``text`` to the characters ``denoProvType`` accepts.

        ``denoProvType`` and ``razonSocialType`` are ``[a-zA-Z0-9\\s]``, so an
        accented partner name is rejected by the schema outright. Decomposing and
        dropping the combining marks is what "no accents" means; anything the
        pattern still cannot carry is dropped rather than replaced, so no
        character appears in the file that the record never held.
        """
        decomposed = unicodedata.normalize("NFKD", text)
        return "".join(
            character
            for character in decomposed
            if character.isascii() and (character.isalnum() or character.isspace())
        )
