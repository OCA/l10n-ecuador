from datetime import date

from odoo.tests import tagged
from odoo.tools import file_open

from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.l10n_ec_account_edi.tests.test_edi_common import TestL10nECEdiCommon

from ..schema import ATS_XSD_PATH

# The same window ATS-06, ATS-07 and ATS-08 use. The catalogues are effective
# dated, so every assertion here that a lookup is *resolved for the period* is
# only meaningful against a period that is not today.
PERIOD = (date(2016, 3, 1), date(2016, 3, 31))
MODERN_PERIOD = (date(2026, 3, 1), date(2026, 3, 31))
EMPTY_PERIOD = (date(2016, 7, 1), date(2016, 7, 31))

#: A fake but **well formed** authorization: ``autorizacionType`` is
#: ``[0-9]{3,49}``, so the fixture states a number that could actually be filed
#: rather than the ``DUMMY_ACCESS_KEY`` the mocked SRI hands back.
AUTHORIZATION = "123456789012"
OTHER_AUTHORIZATION = "210987654321"

#: The access key layout ``l10n_ec_generate_access_key`` produces --
#: ``ddmmyyyy(8) + codDoc(2) + ruc(13) + ambiente(1) + entity(3) + ptoEmi(3) +
#: secuencial(9) + codNumerico(8) + emision(1) + verificador(1)`` = 49 -- so the
#: establishment, the emission point and the sequential occupy ``[24:39]``.
#: ``ACCESS_KEY_PREFIX`` is exactly the 24 characters before that, and the
#: trailing ten stand for ``codNumerico(8) + emision(1) + verificador(1)``.
ACCESS_KEY_PREFIX = "010320161412345678901234"
ACCESS_KEY_TAIL = "0000000000"
ACCESS_KEY_ENTITY = "001"
ACCESS_KEY_POINT = "004"
ACCESS_KEY_SEQUENCE = "000000123"


@tagged("post_install_l10n", "post_install", "-at_install")
class TestL10nEcAtsCollectorAnulados(TestL10nECEdiCommon):
    """One ``detalleAnulados`` row per **contiguous run** of cancelled
    sequentials.

    ``detalleAnuladosType`` (``ats.xsd:1312``) is the only block in the schema
    that files a **range** rather than a document: ``secuencialInicio`` and
    ``secuencialFin``, and no ``fechaEmision`` and no ``fechaRegistro`` to
    reconcile them against anything. Six elements, all obligatory, and the
    sixth is the one that shapes the whole block.

    **A range is an assertion about every document inside it.** The ficha says so
    in as many words (ficha tecnica, §2.5):

    > Se debe considerar que se considerarán anulados los comprobantes que
    > consten dentro del rango informado.

    So a range spanning a document that was *not* cancelled tells the SRI it
    was. Cancelling 5, 6, 7 and 9 is therefore **two** rows -- ``5``-``7`` and
    ``9``-``9`` -- and never one ``5``-``9``. That sentence, not a preference,
    is the core of this suite.

    **``autorizacion`` is singular per row, and each document has its own.**
    ``CLAVE PRIMARIA (2)`` rows 196-201 mark all six elements of this block as
    *componente de clave general*, ``autorizacion`` included, and the ficha
    requires 3 to 49 digits of it on every row. A range therefore cannot claim
    one document's authorization for a set of documents it may not cover, so
    the row key is ``(establecimiento, puntoEmision, tipoComprobante,
    autorizacion)`` and each such group is then split into maximal runs of
    consecutive sequentials.

    The consequence is worth stating plainly, because it is not obvious from
    the schema: **a run can only ever merge documents that share an
    authorization**, and under electronic invoicing each document gets its own
    from the SRI. So in real data every row is a single document with its number
    repeated in both fields -- which is exactly what the ficha prescribes for
    that case:

    > Para anular un solo comprobante, se debe indicar este número en ambos
    > campos.

    Ranges are the physical-invoicing case, where one authorization covered a
    printed batch. The fixture therefore builds the batch explicitly, which is
    the only way to reach the grouping at all.

    **``000`` is refused here even though the schema accepts it.** ``anulados``
    is one of the two carriers ``establecimientoType`` and ``ptoEmisionType``
    constrain with a bare ``[0-9]{3}`` (``ats.xsd:26-30`` and ``36-40``), with
    no ``minExclusive 000``. ``ventasEstablecimiento`` got the rule from the
    schema for free; nothing but this collector stands between a journal set to
    ``000`` and a filed file.
    """

    @classmethod
    @AccountTestInvoicingCommon.setup_country("ec")
    @AccountTestInvoicingCommon.setup_chart_template("ec")
    def setUpClass(cls):
        super().setUpClass()
        cls.Collector = cls.env["l10n.ec.ats.collector"]
        cls.CatalogTable = cls.env["l10n.ec.ats.catalog.table"]
        cls.CatalogEntry = cls.env["l10n.ec.ats.catalog.entry"]
        cls.chart_template = cls.env["account.chart.template"].with_company(cls.company)
        # A sale we issue is validated by the SRI EDI format at posting time, so
        # the company needs its RUC, a loaded certificate, the invoice XML
        # version and a street on the journal's emission address. Same setup,
        # same reason as ATS-07 and ATS-08: it is a property of the documents
        # being collected, not of the collector.
        cls()._setup_edi_company_ec()
        cls.journal_sale = cls.company_data["default_journal_sale"]
        cls.journal_sale.write(
            {
                "l10n_ec_emission_address_id": cls.partner_contact.id,
                "l10n_ec_sri_payment_id": cls.env.ref("l10n_ec.P1").id,
                "l10n_latam_use_documents": True,
                "l10n_ec_entity": "001",
                "l10n_ec_emission": "001",
            }
        )
        cls.tax_vat12 = cls.chart_template.ref("tax_vat_510_sup_01")
        cls.product = cls._priced_product(100.0)

    # ------------------------------------------------------------------
    # Fixtures
    # ------------------------------------------------------------------

    #: Where the auto-generated document numbers start, so the first document a
    #: test creates is ``{entity}-{emission}-000000001`` and the count of
    #: documents a test made is readable off its last one.
    _document_sequence_start = 1

    def _next_document_number(self, journal):
        """The next document number for a document issued through ``journal``.

        Shaped the way this addon reads it -- ``{entity}-{emission}-{seq}``
        with a **nine** digit sequential -- because
        ``account.edi.document._l10n_ec_split_document_number`` pads each half
        and the collector splits on exactly two dashes. The establishment and
        the emission point come from the journal rather than from a constant,
        because ``establecimiento`` and ``puntoEmision`` are key components of
        a row: a document whose number named another establishment would land in
        another row (``test_05``).

        Why not the journal sequence: this block is **arithmetic** on the
        sequential -- a run is one range, a gap splits it, two records claiming
        one number are refused -- and none of that is writable against a number
        the fixture did not choose. Uniqueness comes with it:
        ``l10n_latam_invoice_document`` declares ``_unique_name`` over
        ``(name, journal_id)`` for every posted move.

        A per-instance counter, so it restarts for every test: each one rolls
        back, so a counter outliving a test would only make the numbers depend
        on the order the suite happened to run in.
        """
        journal.ensure_one()
        self._document_sequence = (
            getattr(self, "_document_sequence", self._document_sequence_start - 1) + 1
        )
        return "{}-{}-{:09d}".format(
            journal.l10n_ec_entity or "001",
            journal.l10n_ec_emission or "001",
            self._document_sequence,
        )

    @classmethod
    def _priced_product(cls, price):
        """A saleable product priced at ``price``.

        Priced explicitly rather than reusing ``product_a`` so the fixtures are
        legible: no assertion in this suite is about an amount, and a round
        price keeps the ones that are about identity free of noise.
        """
        return cls.env["product.product"].create(
            {
                "name": f"ATS Anulados {price:.2f}",
                "lst_price": price,
                # The line tax is set per fixture instead, so the product
                # carries none of its own to be cleared on the form.
                "taxes_id": [(5, 0, 0)],
                "property_account_income_id": cls.company_data[
                    "default_account_revenue"
                ].id,
            }
        )

    def _catalog_codes(self, table_code, when):
        """``Tabla`` codes in force on ``when``, read from the catalog.

        ``filtered`` rather than a chained ``search``: ``BaseModel.search`` is
        ``@api.model``, so calling it on a recordset ignores that recordset and
        hands back every era at once, which makes the validity window look like
        no window at all. Asserting the catalog's own facts before anything
        derived from them is the guard ATS-06 needed after shipping that bug and
        ATS-08 kept.
        """
        table = self.CatalogTable.search([("code", "=", table_code)])
        return sorted(
            self.CatalogEntry._applicable_on(when)
            .filtered(lambda entry: entry.table_id == table)
            .mapped("code")
        )

    def _catalog_entry(self, table_code, code):
        table = self.CatalogTable.search([("code", "=", table_code)])
        return self.CatalogEntry.search(
            [("table_id", "=", table.id), ("code", "=", code)], limit=1
        )

    def _document_type(self, value):
        """A document type given either as an xmlid or as a record."""
        return self.env.ref(value) if isinstance(value, str) else value

    def _create_sale(
        self,
        *,
        partner=None,
        taxes=None,
        products=None,
        document_number=None,
        document_type="l10n_ec.ec_dt_01",
        posting_date=PERIOD[0],
        journal=None,
    ):
        """Post one customer invoice, driven through the shared EDI fixture.

        ``_l10n_ec_create_form_move`` is the path every sibling EDI test drives
        a sale through, so it is reused rather than re-derived. ``date`` and
        ``invoice_date`` are set **before** posting because both are readonly on
        a posted move, and the suite needs a 2016 window to prove the catalogues
        are resolved for the reported period rather than for today.

        ``document_number`` defaults to ``None`` -- which means the next number
        from :meth:`_next_document_number`, carrying **this** journal's
        establishment and emission point, rather than whatever the journal
        sequence happened to be at. A test that needs an exact sequential
        passes it and that value wins; :meth:`test_07` then writes ``name`` by
        hand on purpose, which is the one place a repeated number is the point.

        The number is written on the **saved record**, not on the form, and that
        is forced rather than chosen: ``account_move_view.xml`` hides
        ``l10n_latam_document_number`` once the journal has a ``highest_name``,
        so a second ``Form`` in the same test refuses the assignment outright.
        """
        latam_type = self._document_type(document_type)
        issuing_journal = journal or self.journal_sale
        form = self._l10n_ec_create_form_move(
            move_type="out_invoice",
            internal_type="invoice",
            partner=partner or self.partner_ruc,
            taxes=taxes,
            products=products,
            journal=issuing_journal,
            latam_document_type=latam_type,
            use_payment_term=False,
        )
        invoice = form.save()
        if document_type and not invoice.l10n_latam_document_type_id:
            invoice.l10n_latam_document_type_id = latam_type.id
        invoice.write(
            {
                "l10n_latam_document_number": document_number
                or self._next_document_number(issuing_journal)
            }
        )
        invoice.write({"date": posting_date, "invoice_date": posting_date})
        invoice.action_post()
        return invoice

    def _cancel(self, invoice, authorization=AUTHORIZATION):
        """Cancel a posted sale and state its SRI authorization.

        ``button_cancel`` resets to draft and then cancels, and the document
        number survives both steps -- ``_compute_name`` skips a cancelled move
        entirely -- so the triple the collector reads is the triple the SRI was
        given. That is asserted rather than assumed.

        The authorization is stated **through the EDI document**, not on the
        move, and that is not a workaround -- it is where the number lives.

        ``account.move.l10n_ec_authorization_number`` is a stored compute off
        ``edi_document_ids`` (ATS-02), and ``button_cancel`` **deletes** those
        documents, so the mirror recomputes to nothing for every cancelled move.
        Writing the mirror directly is fighting that recompute: the value sits
        in the cache, then a flush triggered by the *next* invoice runs the
        compute and discards it. So the fixture creates the ``cancelled`` EDI
        document the real flow would leave behind and writes the number on it,
        where the compute agrees with the fixture instead of overruling it.

        The mocked SRI never answers, so nothing fills the number in on its own.
        """
        invoice.button_cancel()
        self.assertEqual(invoice.state, "cancel")
        self.assertTrue(invoice.posted_before, "it was issued before it was cancelled")
        self.assertTrue(
            invoice.l10n_latam_document_number,
            "a cancelled posted document keeps its document number",
        )
        self.assertFalse(
            invoice.edi_document_ids,
            "cancelling deletes the EDI documents the mirror is computed from",
        )
        if authorization:
            self.env["account.edi.document"].create(
                {
                    "move_id": invoice.id,
                    "edi_format_id": self.env.ref(
                        "l10n_ec_account_edi.edi_format_ec_sri"
                    ).id,
                    "state": "cancelled",
                    "l10n_ec_authorization_number": authorization,
                }
            )
            self.assertEqual(invoice.l10n_ec_authorization_number, authorization)
        return invoice

    def _create_cancelled_sale(self, *, authorization=AUTHORIZATION, **kwargs):
        """Post one sale and cancel it, in the order the real flow happens."""
        return self._cancel(self._create_sale(**kwargs), authorization=authorization)

    def _create_cancelled_credit_note(self, *, authorization=AUTHORIZATION):
        """A posted ``out_refund`` cancelled, carrying the sign Odoo gives it.

        Built the way ATS-08's ``_create_credit_note`` builds one -- created and
        posted as an invoice, then retyped -- and for the same reason: choosing a
        credit-note document type on a **new** EC invoice makes the form require
        ``l10n_ec_legacy_document_number``, which is the external-document field
        of a vendor document and has nothing to do with this one.

        Retyping after posting also leaves ``l10n_latam_document_number`` alone:
        the compute splits the current document type's prefix off ``name``, and
        both prefixes sit in front of the same triple.
        """
        note = self._create_sale()
        note.write(
            {
                "move_type": "out_refund",
                "l10n_latam_document_type_id": self.env.ref("l10n_ec.ec_dt_04").id,
            }
        )
        self.assertEqual(note.move_type, "out_refund")
        self.assertEqual(note.l10n_latam_document_type_id.code, "04")
        return self._cancel(note, authorization=authorization)

    def _collect(self, period=PERIOD):
        return self.Collector.collect_anulados_with_errors(
            self.company, period[0], period[1]
        )

    def _ranges(self, period=PERIOD):
        """The ``(secuencialInicio, secuencialFin)`` of every filed row."""
        rows, errors = self._collect(period=period)
        self.assertFalse(errors, errors)
        return [(row["secuencialInicio"], row["secuencialFin"]) for row in rows]

    def _sequential_of(self, invoice):
        """The sequential this collector reads off ``invoice``."""
        return self.Collector._l10n_ec_triple_from_document_number(invoice)[2]

    # ------------------------------------------------------------------
    # The fixture numbers its own documents
    # ------------------------------------------------------------------

    def test_the_sale_fixture_gives_every_document_a_number_of_its_own(self):
        """Consecutive, and therefore usable for the contiguity assertions.

        Every test in this block is arithmetic on the ``secuencial``: a run is
        one range, a gap splits it, and two records claiming one number are
        refused. None of that is writable against a number the fixture did not
        choose, which is why the counter is deterministic rather than a
        timestamp. Uniqueness comes with it:
        ``l10n_latam_invoice_document`` declares ``_unique_name`` over
        ``(name, journal_id)`` for every posted move.
        """
        invoices = [self._create_sale() for _index in range(3)]
        self.assertEqual(
            [self._sequential_of(invoice) for invoice in invoices],
            ["000000001", "000000002", "000000003"],
        )
        # An explicit number wins, which is what the access-key fallback test
        # and the duplicate-sequential guard test need.
        explicit = self._create_sale(document_number="001-001-000000900")
        self.assertEqual(self._sequential_of(explicit), "000000900")
        self.assertEqual(len({invoice.name for invoice in invoices}), 3)

    # ------------------------------------------------------------------
    # Contiguity: the core of the block
    # ------------------------------------------------------------------

    def test_01_three_cancelled_sequentials_in_a_row_are_one_range(self):
        """ficha §2.5: *"Cuando se registra un grupo de comprobantes que posean
        secuencial seguido ... el número del primer comprobante a anular"* and
        *"el número del último comprobante a anular"*.

        One range from the first to the last, and not three rows: three
        documents sharing one authorization and holding consecutive sequentials
        is the case the range exists for.
        """
        cancelled = [self._create_cancelled_sale() for _index in range(3)]
        sequences = [self._sequential_of(invoice) for invoice in cancelled]
        numbers = [int(sequence) for sequence in sequences]
        # The fixture's own facts, before anything derived from them.
        self.assertEqual(numbers, list(range(numbers[0], numbers[0] + 3)))
        self.assertEqual(
            {invoice.l10n_ec_authorization_number for invoice in cancelled},
            {AUTHORIZATION},
        )

        rows, errors = self._collect()
        self.assertFalse(errors, errors)
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(rows[0]["secuencialInicio"], sequences[0])
        self.assertEqual(rows[0]["secuencialFin"], sequences[-1])
        self.assertEqual(rows[0]["autorizacion"], AUTHORIZATION)

    def test_02_a_gap_splits_the_range_because_the_range_asserts_every_document(self):
        """ficha §2.5: *"se considerarán anulados los comprobantes que consten
        dentro del rango informado"*.

        Four consecutive sequentials, the **second** left posted and the other
        three cancelled. The honest output is **two** rows -- ``1``-``1`` and
        ``3``-``4`` -- because one ``1``-``4`` range would assert to the SRI that
        the still-valid middle document was cancelled. This is the assertion the
        whole block rests on, so it is pinned as a list of ranges rather than as
        a row count: a collector that emitted a single ``1``-``4`` row would pass
        a ``len(rows) == 1`` assertion.
        """
        first, kept, third, fourth = (self._create_sale() for _index in range(4))
        sequences = [
            self._sequential_of(invoice) for invoice in (first, kept, third, fourth)
        ]
        numbers = [int(sequence) for sequence in sequences]
        # The fixture's own facts, before anything derived from them: four
        # consecutive sequentials, the second of them still posted.
        self.assertEqual(numbers, list(range(numbers[0], numbers[0] + 4)))
        self.assertEqual(kept.state, "posted")
        self._cancel(first)
        self._cancel(third)
        self._cancel(fourth)

        self.assertEqual(
            self._ranges(),
            [
                (sequences[0], sequences[0]),
                (sequences[2], sequences[3]),
            ],
        )
        # The gap is real: the range that was refused would have covered exactly
        # the document that is still valid.
        self.assertEqual(numbers[2] - 1, numbers[1])

    def test_03_a_single_cancelled_document_repeats_its_number_in_both_fields(self):
        """ficha §2.5: *"Para anular un solo comprobante, se debe indicar este
        número en ambos campos."*

        ``ESQUEMA`` row 211 states the opposite -- *"debe ser mayor a
        secuencialInicio"* -- and the ficha prose is the operative text: it is
        the sentence written about this exact case, and a strict reading of the
        table would make cancelling one document impossible to file.
        """
        invoice = self._create_cancelled_sale()
        sequence = self._sequential_of(invoice)
        rows, errors = self._collect()
        self.assertFalse(errors, errors)
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(rows[0]["secuencialInicio"], sequence)
        self.assertEqual(rows[0]["secuencialFin"], sequence)

    def test_04_each_document_authorization_of_its_own_means_each_row_is_one_document(
        self,
    ):
        """The consequence of keying on the authorization, stated as a test.

        Two consecutive sequentials, two authorizations. They cannot be one row:
        the row's ``autorizacion`` would then be one document's number claimed
        for both, which is the substitution this collector exists to refuse.
        This is what real electronic invoicing looks like -- the SRI issues one
        authorization per document -- so it is the common case, not an edge.
        """
        first = self._create_cancelled_sale(authorization=AUTHORIZATION)
        second = self._create_cancelled_sale(authorization=OTHER_AUTHORIZATION)
        self.assertEqual(
            int(self._sequential_of(second)), int(self._sequential_of(first)) + 1
        )
        rows, errors = self._collect()
        self.assertFalse(errors, errors)
        self.assertEqual(
            sorted(row["autorizacion"] for row in rows),
            sorted([AUTHORIZATION, OTHER_AUTHORIZATION]),
        )
        for row in rows:
            self.assertEqual(row["secuencialInicio"], row["secuencialFin"])

    def test_05_a_different_establishment_is_a_different_group(self):
        """The other three halves of the row key.

        ``establecimiento`` and ``puntoEmision`` are ``componente de clave
        general`` in ``CLAVE PRIMARIA (2)`` rows 197-198, so a run never spans
        them. Two journals under two establishments, sharing one authorization
        and consecutive sequentials, must still be two rows.
        """
        second_journal = self.journal_sale.copy(
            {"l10n_ec_entity": "002", "l10n_ec_emission": "001", "code": "SAL2"}
        )
        first = self._create_cancelled_sale()
        other = self._create_cancelled_sale(journal=second_journal)
        self.assertEqual(
            self.Collector._l10n_ec_triple_from_document_number(first)[0], "001"
        )
        self.assertEqual(
            self.Collector._l10n_ec_triple_from_document_number(other)[0], "002"
        )

        rows, errors = self._collect()
        self.assertFalse(errors, errors)
        self.assertEqual(sorted(row["establecimiento"] for row in rows), ["001", "002"])
        for row in rows:
            self.assertEqual(row["autorizacion"], AUTHORIZATION)

    def test_06_a_different_document_type_is_a_different_group(self):
        """``tipoComprobante`` is the fourth half, and it is the document's own
        code rather than a fixed one.

        A cancelled invoice and a cancelled credit note holding consecutive
        sequentials under one authorization are two rows: ``CLAVE PRIMARIA (2)``
        row 196 marks ``tipoComprobante`` a general key component, so folding
        them would put a code in the file that is true of neither row.
        """
        invoice = self._create_cancelled_sale()
        note = self._create_cancelled_credit_note()
        self.assertEqual(
            int(self._sequential_of(note)),
            int(self._sequential_of(invoice)) + 1,
        )
        rows, errors = self._collect()
        self.assertFalse(errors, errors)
        self.assertEqual(sorted(row["tipoComprobante"] for row in rows), ["01", "04"])

    def test_07_two_records_claiming_one_document_number_file_it_once(self):
        """The row's primary key is all six elements, so it may not repeat.

        Two cancelled records carrying the same document number would produce two
        identical ranges -- the same six-element key twice, which ``CLAVE
        PRIMARIA`` forbids. The second is reported instead, because two records
        claiming one document is a data defect somewhere else and the file
        should not carry it twice.
        """
        first = self._create_cancelled_sale()
        twin = self._create_cancelled_sale()
        # Two records claiming one document: the copy route cannot do it, because
        # ``posted_before`` is ``copy=False`` and a copied invoice has never been
        # issued. Writing ``name`` is what does, and it is the field the document
        # number is computed from -- the same field the collector reads.
        twin.name = first.name
        self.assertEqual(
            self._sequential_of(twin),
            self._sequential_of(first),
            "the twin carries the same document number",
        )

        rows, errors = self._collect()
        self.assertEqual(len(rows), 1, rows)
        duplicates = [error for error in errors if error["field"] == "secuencialInicio"]
        self.assertEqual(len(duplicates), 1, errors)
        self.assertEqual(duplicates[0]["move"], twin)
        self.assertIn(twin.display_name, str(duplicates[0]["message"]))

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def test_08_a_cancelled_draft_is_not_a_cancelled_document(self):
        """A draft was never issued and never authorized.

        Odoo shows it as ``/`` and ``posted_before`` is the record of the fact:
        ``account.move`` sets it in ``_post`` and nothing else, so a move
        cancelled straight from draft never had it. ``state = 'cancel'`` alone
        does **not** exclude it -- ``button_cancel`` accepts a draft -- which is
        why the selection needs this second condition.
        """
        draft = self._l10n_ec_prepare_edi_out_invoice(
            partner=self.partner_ruc,
            taxes=self.tax_vat12,
            products=self.product,
            latam_document_type=self.env.ref("l10n_ec.ec_dt_01"),
        )
        self.assertEqual(draft.state, "draft")
        draft.button_cancel()
        self.assertEqual(draft.state, "cancel")
        self.assertFalse(draft.posted_before, "it was never posted")

        self.assertEqual(
            self.Collector._l10n_ec_anulados_moves(self.company, PERIOD[0], PERIOD[1]),
            self.env["account.move"],
        )
        rows, errors = self._collect()
        self.assertEqual(rows, [])
        self.assertEqual(errors, [], "a draft that was never issued is not an error")

    def test_09_only_cancelled_sales_documents_of_the_period_are_collected(self):
        """``move_type in ('out_invoice', 'out_refund')``, ``state == 'cancel'``.

        A posted sale, a cancelled vendor bill and a cancelled document outside
        the window are all outside this block: it files **our own** cancelled
        sales, and ``fechaRegistro`` -- the accounting date -- is the only date a
        row can be selected by, since ``detalleAnuladosType`` carries no date at
        all.
        """
        cancelled = self._create_cancelled_sale()
        posted = self._create_sale()
        self.assertEqual(posted.state, "posted")
        outside = self._create_cancelled_sale(posting_date=date(2016, 5, 10))

        journal_purchase = self.company_data["default_journal_purchase"]
        journal_purchase.write(
            {
                "l10n_ec_emission_address_id": self.partner_contact.id,
                "l10n_ec_sri_payment_id": self.env.ref("l10n_ec.P1").id,
                "l10n_latam_use_documents": True,
                "l10n_ec_entity": "001",
                "l10n_ec_emission": "001",
            }
        )
        bill = self._l10n_ec_create_in_invoice(
            self.partner_ruc,
            taxes=self.tax_vat12,
            journal=journal_purchase,
            latam_document_type=self.env.ref("l10n_ec.ec_dt_01"),
            l10n_latam_document_number="001-001-000000900",
        )
        bill.write({"date": PERIOD[0], "invoice_date": PERIOD[0]})
        bill.l10n_ec_tax_support = "01"
        bill.action_post()
        bill.button_cancel()

        selected = self.Collector._l10n_ec_anulados_moves(
            self.company, PERIOD[0], PERIOD[1]
        )
        self.assertEqual(selected, cancelled)
        self.assertNotIn(posted, selected)
        self.assertNotIn(bill, selected)
        self.assertNotIn(outside, selected)

    def test_10_a_credit_note_is_a_cancelled_document_and_files_under_its_own_type(
        self,
    ):
        """``Tabla 4`` code ``18`` is *"Documentos autorizados utilizados en
        ventas **excepto N/C N/D**"* -- so a credit note is out of that class, and
        the row must not claim it.

        ``ESQUEMA`` row 207 asks for *"uno de los códigos de la tabla 4, **sin
        filtro alguno**"*: no ``codSustento``, no transaction filter. Carrying
        the document's own code is what makes a cancelled credit note
        reportable at all; a fixed ``18`` would assert the cancelled document
        was not a credit note.
        """
        entry = self._catalog_entry("04", "18")
        self.assertTrue(entry, "Tabla 4 must publish code 18 at all")
        self.assertIn("N/D", entry.description)
        self.assertIn("N/C", entry.description)

        note = self._create_cancelled_credit_note()
        self.assertEqual(note.move_type, "out_refund")
        rows, errors = self._collect()
        self.assertFalse(errors, errors)
        self.assertEqual(sorted(row["tipoComprobante"] for row in rows), ["04"])

    def test_11_a_cancelled_credit_note_does_not_merge_with_a_cancelled_invoice(self):
        """The companion to :meth:`test_10`: a reversal in the same range set.

        ``out_refund`` is selected alongside ``out_invoice`` exactly as it is on
        the ``ventas`` block -- a reversal is a document of its own, filed under
        its own type, and this block has no other way to say that a sale was
        credited. Two consecutive cancelled sequentials of different types stay
        two rows.
        """
        invoice = self._create_cancelled_sale()
        note = self._create_cancelled_credit_note()
        self.assertEqual(
            int(self._sequential_of(note)),
            int(self._sequential_of(invoice)) + 1,
        )
        rows, errors = self._collect()
        self.assertFalse(errors, errors)
        self.assertEqual(sorted(row["tipoComprobante"] for row in rows), ["01", "04"])

    def test_12_an_empty_period_yields_an_empty_list_and_no_error(self):
        """Nothing cancelled is a legitimate month, not a failure."""
        self._create_cancelled_sale()
        rows, errors = self._collect(period=EMPTY_PERIOD)
        self.assertEqual(rows, [])
        self.assertEqual(errors, [])
        self.assertEqual(len(self._collect()[0]), 1, "the document is in March")

    # ------------------------------------------------------------------
    # Where the numbers come from
    # ------------------------------------------------------------------

    def test_13_the_sequential_is_split_out_of_the_recorded_document_number(self):
        """``l10n_latam_document_number`` through the addon's own splitter.

        ``_l10n_ec_split_document_number`` is the one place that decides what a
        well formed number looks like, and it pads each half the way the ficha
        requires -- so ``001-001-5`` reads back as ``000000005``, which
        ``secuencialType``'s ``\\d{1,9}`` accepts.
        """
        invoice = self._create_cancelled_sale()
        self.assertTrue(invoice.l10n_latam_document_number.startswith("001-001-"))
        entity, point, sequence = self.env[
            "account.edi.document"
        ]._l10n_ec_split_document_number(invoice.l10n_latam_document_number)
        self.assertEqual((entity, point), ("001", "001"))
        self.assertEqual(len(sequence), 9)
        self.assertTrue(sequence.isdigit())
        self.assertGreaterEqual(int(sequence), 1)

        rows, errors = self._collect()
        self.assertFalse(errors, errors)
        self.assertEqual(rows[0]["secuencialInicio"], sequence)
        self.assertEqual(rows[0]["establecimiento"], entity)
        self.assertEqual(rows[0]["puntoEmision"], point)

    def test_14_the_access_key_is_the_recovery_path_and_the_fallback_applies(self):
        """The same seam ``compras`` uses, and it is a fallback, never a source.

        ``l10n_ec_generate_access_key`` lays a key out as ``ddmmyyyy(8) +
        codDoc(2) + ruc(13) + ambiente(1) + entity(3) + ptoEmi(3) + secuencial(9)
        + codNumerico(8) + emision(1) + verificador(1)`` = 49 characters, so the
        triple occupies ``[24:39]``. Asserted before anything is read out of it.
        """
        invoice = self._create_cancelled_sale()
        access_key = (
            ACCESS_KEY_PREFIX
            + ACCESS_KEY_ENTITY
            + ACCESS_KEY_POINT
            + ACCESS_KEY_SEQUENCE
            + ACCESS_KEY_TAIL
        )
        self.assertEqual(len(access_key), 49)
        self.assertTrue(access_key.isdigit())
        invoice.l10n_ec_xml_access_key = access_key
        invoice.name = False
        self.assertFalse(
            invoice.l10n_latam_document_number,
            "the recorded number is gone, so the fallback is reachable",
        )

        self.assertEqual(
            self.Collector._l10n_ec_triple_from_document_number(invoice), False
        )
        self.assertEqual(
            self.Collector._l10n_ec_triple_from_access_key(invoice),
            (ACCESS_KEY_ENTITY, ACCESS_KEY_POINT, ACCESS_KEY_SEQUENCE),
        )
        rows, errors = self._collect()
        self.assertFalse(errors, errors)
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(rows[0]["establecimiento"], ACCESS_KEY_ENTITY)
        self.assertEqual(rows[0]["puntoEmision"], ACCESS_KEY_POINT)
        self.assertEqual(rows[0]["secuencialInicio"], ACCESS_KEY_SEQUENCE)
        self.assertEqual(rows[0]["secuencialFin"], ACCESS_KEY_SEQUENCE)

    def test_15_a_document_with_no_number_at_all_blocks_and_says_so(self):
        """Nothing is substituted, and the refusal names the document.

        Neither the recorded number nor a 49 digit key: there is no triple to
        read, so the row would have to invent one. The message points at the
        document rather than at a field list, because that is what the user has
        to go and fix.
        """
        invoice = self._create_cancelled_sale()
        invoice.l10n_ec_xml_access_key = ""
        invoice.name = False
        self.assertFalse(invoice.l10n_latam_document_number)

        rows, errors = self._collect()
        self.assertEqual(rows, [])
        self.assertEqual([error["field"] for error in errors], ["establecimiento"])
        self.assertEqual(errors[0]["move"], invoice)
        self.assertIn(invoice.display_name, str(errors[0]["message"]))

    def test_16_a_sequential_that_is_not_a_number_blocks_the_row(self):
        """A range is made of numbers, so a non numeric one cannot open one.

        ``_l10n_ec_triple_from_document_number`` accepts any three non-empty
        halves, which is right for ``compras`` -- the builder is where a bad
        ``secuencial`` is caught against the schema. A range needs the value
        **here**, to judge contiguity against the previous document, so a
        non-numeric sequential is refused at the point where it stops being
        usable rather than reaching the file.
        """
        invoice = self._create_cancelled_sale()
        invoice.name = "Fact 001-001-000000ABC"
        self.assertEqual(
            self.Collector._l10n_ec_triple_from_document_number(invoice)[2],
            "000000ABC",
        )
        rows, errors = self._collect()
        self.assertEqual(rows, [])
        self.assertEqual([error["field"] for error in errors], ["secuencialInicio"])
        self.assertEqual(errors[0]["move"], invoice)

    # ------------------------------------------------------------------
    # The 000 rule, where the schema is no help at all
    # ------------------------------------------------------------------

    def test_17_a_zero_establishment_is_rejected_and_named(self):
        """``establecimientoType`` is a bare ``[0-9]{3}`` (``ats.xsd:26-30``).

        Nothing upstream stops it: ``l10n_ec_base``'s
        ``_constrains_l10n_ec_entity_emission`` checks only the length and
        ``isnumeric()``, and ``"000"`` satisfies both. Unlike
        ``ventasEstablecimiento``, a file carrying one here breaks **no** schema
        constraint -- it only breaks the ficha.
        """
        journal = self.journal_sale.copy(
            {"l10n_ec_entity": "000", "l10n_ec_emission": "001", "code": "SAL0"}
        )
        self.assertEqual(journal.l10n_ec_entity, "000")
        self.assertTrue(journal.l10n_ec_entity.isnumeric())
        self.assertGreaterEqual(len(journal.l10n_ec_entity), 3)

        invoice = self._create_cancelled_sale(journal=journal)
        self.assertEqual(
            self.Collector._l10n_ec_triple_from_document_number(invoice)[0], "000"
        )
        rows, errors = self._collect()
        self.assertEqual(rows, [])
        self.assertEqual([error["field"] for error in errors], ["establecimiento"])
        self.assertEqual(errors[0]["move"], invoice)
        self.assertIn(invoice.display_name, str(errors[0]["message"]))
        self.assertIn("000", str(errors[0]["message"]))

    def test_18_a_zero_emission_point_is_rejected_and_named(self):
        """``ptoEmisionType`` (``ats.xsd:36-40``) is the same bare ``[0-9]{3}``."""
        journal = self.journal_sale.copy(
            {"l10n_ec_entity": "001", "l10n_ec_emission": "000", "code": "SAL0P"}
        )
        invoice = self._create_cancelled_sale(journal=journal)
        self.assertEqual(
            self.Collector._l10n_ec_triple_from_document_number(invoice)[1], "000"
        )
        rows, errors = self._collect()
        self.assertEqual(rows, [])
        self.assertEqual([error["field"] for error in errors], ["puntoEmision"])
        self.assertEqual(errors[0]["move"], invoice)
        self.assertIn("000", str(errors[0]["message"]))

    def test_19_a_rejected_code_does_not_leak_into_a_valid_group(self):
        """A refused establishment is skipped, not folded into a neighbour.

        The document whose establishment is ``000`` is reported and left out; the
        documents of the real establishment still file. Putting the refused one
        in with them would file ``000``'s sequential under ``001``.
        """
        journal = self.journal_sale.copy(
            {"l10n_ec_entity": "000", "l10n_ec_emission": "001", "code": "SAL0"}
        )
        refused = self._create_cancelled_sale(journal=journal)
        # A copied journal draws from its **own** sequence, so both
        # establishments open at ``000000001``. One posted sale on the real
        # journal pushes the document that must still file past it, which is what
        # makes "the refused sequential is not in the valid row" a statement
        # about two different numbers rather than a coincidence.
        self._create_sale()
        valid = self._create_cancelled_sale()
        self.assertNotEqual(self._sequential_of(valid), self._sequential_of(refused))

        rows, errors = self._collect()
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(rows[0]["establecimiento"], "001")
        self.assertEqual(rows[0]["secuencialInicio"], self._sequential_of(valid))
        self.assertEqual(rows[0]["secuencialFin"], self._sequential_of(valid))
        self.assertEqual([error["field"] for error in errors], ["establecimiento"])
        self.assertEqual(errors[0]["move"], refused)

    # ------------------------------------------------------------------
    # Blocking conditions
    # ------------------------------------------------------------------

    def test_20_a_missing_authorization_blocks_the_row_and_emits_no_placeholder(self):
        """§5.9.1: Enterprise writes ``'9999999999'`` here; ATS refuses.

        The number in the file has to be one the SRI issued, and a fabricated
        one is worse than a missing file. Asserted structurally: the row is
        absent, so there is no value at all -- not an empty string, not a
        placeholder, not the document's own access key standing in.
        """
        self._create_cancelled_sale(authorization=None)
        self.assertEqual(self._collect()[0], [])
        rows, errors = self._collect()
        self.assertEqual([error["field"] for error in errors], ["autorizacion"])
        self.assertNotIn("9999999999", str(errors[0]["message"]))

    def test_21_tipo_comprobante_is_checked_against_tabla_4_for_the_reported_period(
        self,
    ):
        """The temporal guard, and the regression test for the chained-``search``
        defect ATS-06 shipped and ATS-08 re-pinned.

        ``Tabla 4`` states no ``Fecha de vigencia`` of its own -- the sheet
        spells that column ``vacío`` in all forty rows -- so the window is set
        here to the one the SRI's own history would give the row: in force from
        2020, absent before.
        """
        self.assertIn("1", self._catalog_codes("04", MODERN_PERIOD[0]))
        self._catalog_entry("04", "1").date_start = date(2020, 1, 1)
        # The catalog's own facts, asserted before anything derived from them.
        self.assertIn("1", self._catalog_codes("04", MODERN_PERIOD[0]))
        self.assertNotIn("1", self._catalog_codes("04", PERIOD[0]))

        self._create_cancelled_sale()
        rows, errors = self._collect()
        self.assertEqual(rows, [])
        self.assertEqual([error["field"] for error in errors], ["tipoComprobante"])
        self.assertIn("1", str(errors[0]["message"]))

    def test_22_the_same_document_type_is_accepted_for_a_period_that_covers_it(self):
        """The counterpart to :meth:`test_21`.

        Without it the guard above would pass for the wrong reason: a collector
        that resolved ``Tabla 4`` for *today* would refuse March 2016 and file
        March 2026, and a collector that ignored the table altogether would
        refuse neither.
        """
        self._catalog_entry("04", "1").date_start = date(2020, 1, 1)
        invoice = self._create_cancelled_sale(posting_date=MODERN_PERIOD[0])
        rows, errors = self._collect(period=MODERN_PERIOD)
        self.assertFalse(errors, errors)
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(rows[0]["tipoComprobante"], "01")
        self.assertEqual(rows[0]["secuencialInicio"], self._sequential_of(invoice))

    def test_23_a_document_type_outside_tabla_4_blocks_the_row(self):
        """A code the SRI never published cannot be filed.

        Every document type the EC localization ships *is* a ``Tabla 4`` code
        and a draft cannot be given one that is not, so the code is changed
        after posting -- what a retired catalogue row looks like by filing time.
        """
        self.assertNotIn("99", self._catalog_codes("04", PERIOD[0]))
        invoice = self._create_cancelled_sale()
        invoice.l10n_latam_document_type_id.code = "99"
        self.assertEqual(invoice.l10n_latam_document_type_id.code, "99")

        rows, errors = self._collect()
        self.assertEqual(rows, [])
        self.assertEqual([error["field"] for error in errors], ["tipoComprobante"])
        self.assertIn("99", str(errors[0]["message"]))

    def test_24_fecha_registro_outside_the_reported_month_blocks(self):
        """A window wider than a month is refused, not silently narrowed.

        ``detalleAnuladosType`` carries no ``fechaRegistro`` -- and no
        ``fechaEmision`` -- so ``move.date`` is the **only** date a row can be
        selected by, and the ficha says the block holds *"todos los
        comprobantes del mes"*. A caller that hands over a quarter gets the
        month's rows plus a named refusal for every document outside it, which
        is what ATS-08's ``ventasEstablecimiento`` block already does. Dropping
        them silently would produce a file that is quietly missing documents.
        """
        self._create_cancelled_sale(posting_date=date(2016, 2, 15))
        rows, errors = self._collect(period=(date(2016, 1, 1), date(2016, 3, 31)))
        self.assertEqual(rows, [])
        self.assertEqual([error["field"] for error in errors], ["fechaRegistro"])

    def test_25_one_bad_document_does_not_hide_the_others(self):
        """Errors and values travel together, as in every sibling block.

        One month, one unfileable document and one good one: the caller sees the
        row it can honestly produce **and** the document that stopped it, rather
        than a silent omission or an empty list.
        """
        good = self._create_cancelled_sale()
        self._create_cancelled_sale(authorization=None)

        rows, errors = self._collect()
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(rows[0]["secuencialInicio"], self._sequential_of(good))
        self.assertEqual([error["field"] for error in errors], ["autorizacion"])

    # ------------------------------------------------------------------
    # Row shape
    # ------------------------------------------------------------------

    def test_26_the_row_keys_are_exactly_the_ats_element_names(self):
        """ATS-10 is a straight mapping, so the keys must be the XSD names.

        ``detalleAnuladosType`` (``ats.xsd:1312-1321``) is a strict sequence of
        six required elements. The ESQUEMA sheet spells the sixth
        ``autorización`` **with** an accent and the schema spells it
        ``autorizacion`` **without**; the schema wins, because the schema is what
        the file has to satisfy. Asserted here so the spelling cannot drift with
        the documentation.
        """
        self._create_cancelled_sale()
        rows, errors = self._collect()
        self.assertFalse(errors, errors)
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(
            set(rows[0]),
            {
                "tipoComprobante",
                "establecimiento",
                "puntoEmision",
                "secuencialInicio",
                "secuencialFin",
                "autorizacion",
            },
        )
        for absent in ("fechaEmision", "fechaRegistro", "codSustento", "air"):
            self.assertNotIn(absent, rows[0])

    def test_27_every_error_carries_every_key_of_the_block_contract(self):
        """``move``, ``journal``, ``field`` and ``message``, on every error.

        ATS-08 documented that contract for the blocks it wrote; the two blocks
        before it build their dicts without ``journal``. This block honours it,
        so a consumer can read either key without a ``KeyError``, and the
        assertion is made over one error of each kind the block can raise.

        The window is a quarter on purpose: a document outside the reported month
        is **selected** only when the caller asks for it, so a March report
        cannot raise ``fechaRegistro`` at all.
        """
        self._create_cancelled_sale(authorization=None)
        self._create_cancelled_sale(posting_date=date(2016, 2, 15))
        journal = self.journal_sale.copy(
            {"l10n_ec_entity": "000", "l10n_ec_emission": "001", "code": "SAL0"}
        )
        self._create_cancelled_sale(journal=journal)

        _rows, errors = self._collect(period=(date(2016, 1, 1), date(2016, 3, 31)))
        self.assertTrue(errors)
        self.assertEqual(
            {error["field"] for error in errors},
            {"autorizacion", "fechaRegistro", "establecimiento"},
        )
        for error in errors:
            self.assertEqual(set(error), {"move", "journal", "field", "message"})
            self.assertTrue(error["move"], "every problem here names its document")
            self.assertFalse(
                error["journal"],
                "no problem in this block is about a journal rather than a document",
            )

    def test_28_the_schema_does_not_constrain_this_block_but_the_ficha_still_binds(
        self,
    ):
        """§5.4b: the two validation layers, and the gap between them.

        ``detalleAnuladosType`` is a strict six-element sequence, so nothing can
        be quietly dropped. What the schema cannot do is stop a ``000`` -- the
        two carriers this block uses are exactly the pair ``establecimientoType``
        and ``ptoEmisionType``, which constrain nothing but length -- and what it
        cannot see at all is the reported period. Both are the collector's job,
        and this pins the gap as still open rather than quietly closed.

        Read from the shipped ``ats.xsd`` rather than from a helper, so the
        assertion is about the artifact the file is validated against.
        """
        with file_open(ATS_XSD_PATH, "rb") as xsd_file:
            xsd = xsd_file.read().decode("utf-8")
        block = xsd[xsd.index('<xsd:complexType name="detalleAnuladosType">') :]
        block = block[: block.index("</xsd:complexType>")]
        for name in (
            "tipoComprobante",
            "establecimiento",
            "puntoEmision",
            "secuencialInicio",
            "secuencialFin",
            "autorizacion",
        ):
            self.assertIn(f'<xsd:element name="{name}"', block, name)
        # A strict sequence of six required elements: no ``minOccurs="0"``
        # anywhere inside it.
        self.assertNotIn('minOccurs="0"', block)
        self.assertNotIn("autorización", block)

        for type_name in ("establecimientoType", "ptoEmisionType"):
            declaration = xsd[xsd.index(f'<xsd:simpleType name="{type_name}">') :]
            declaration = declaration[: declaration.index("</xsd:simpleType>")]
            self.assertIn('<xsd:pattern value="[0-9]{3}" />', declaration)
            self.assertNotIn("minExclusive", declaration)
