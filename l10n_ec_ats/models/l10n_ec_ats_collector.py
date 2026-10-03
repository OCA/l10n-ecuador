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
    def _l10n_ec_id_prov(self, partner, report):
        """``idProv``: the supplier's identification, placeholders rejected.

        The ficha names the sentinels for an exterior identification: they are not
        an identification of anybody. Consumer Final is handled in
        :meth:`_l10n_ec_tp_id_prov`, which has to refuse it anyway; what remains
        here is the all-zero placeholder.
        """
        vat = (partner.vat or "").strip()
        if not vat:
            return False
        if set(vat) == {"0"}:
            report(
                "idProv",
                self.env._(
                    "%(vat)s is not a real identification number, so "
                    "%(partner)s cannot be reported as a supplier.",
                    vat=vat,
                    partner=partner.display_name,
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
    def _l10n_ec_tabla_14_entry(self, partner, reported):
        """The ``Tabla 14`` row matching the supplier's nature, or an empty set."""
        keyword = TABLA_14_KEYWORD_BY_COMPANY_TYPE.get(partner.company_type)
        if not keyword:
            return self.env["l10n.ec.ats.catalog.entry"]
        return self._l10n_ec_applicable_entries("14", reported).filtered(
            lambda entry: keyword in (entry.description or "").upper()
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
    def _l10n_ec_withholding_lines(self, move):
        """The withholding basis lines booked against ``move``.

        ``l10n_ec_invoice_withhold_id`` is the only link a withholding carries
        back to the document it supports, so the collector follows it rather than
        guessing from dates or partners. Draft withholdings are ignored: a
        withholding the company has not filed does not reduce the purchase.
        """
        withholdings = move.l10n_ec_withhold_ids.filtered(
            lambda withhold: withhold.state == "posted"
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
        for line in self._l10n_ec_withholding_lines(move):
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
        for line in self._l10n_ec_withholding_lines(move):
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
