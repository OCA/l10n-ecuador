from datetime import date

from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.l10n_ec_account_edi.tests.test_edi_common import TestL10nECEdiCommon

# A period inside every regime these tests touch: ``Tabla 20`` publishes the
# electronic emission code from 2016-01-01, ``Tabla 13`` still carries the
# 2013 payment forms, and ``Tabla 5`` is at its 2016 state.
PERIOD = (date(2016, 3, 1), date(2016, 3, 31))
MODERN_PERIOD = (date(2026, 3, 1), date(2026, 3, 31))
# Before ``Tabla 20`` published the electronic emission code. Used to prove the
# emission type is resolved *for the reported period* and not for today.
BEFORE_ELECTRONIC_PERIOD = (date(2015, 12, 1), date(2015, 12, 31))
EMPTY_PERIOD = (date(2016, 7, 1), date(2016, 7, 31))
# ``Tabla 13`` publishes the debit-card form from 2016-05-01, so this is the
# period in which it is in force and the reported period in which it is not.
DEBIT_CARD_PERIOD = (date(2016, 6, 1), date(2016, 6, 30))


@tagged("post_install_l10n", "post_install", "-at_install")
class TestL10nEcAtsCollectorVentas(TestL10nECEdiCommon):
    """One ``detalleVentas`` row per client and document type, not per document.

    ``ventas`` is the one ATS block the SRI aggregates: ``numeroComprobantes``
    carries the count of documents folded into the row, and the ficha calls for
    the amounts of *all* of them. Two invoices to the same client under the same
    document type are therefore one row with a count of two, which is the single
    structural difference from the ``compras`` collector.

    The other rule every assertion leans on is the one this project exists to
    enforce: a missing value is reported as a blocking problem naming the
    document and the field, never substituted.
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
        # Unlike a vendor bill, a sale we issue is validated by the SRI EDI
        # format at posting time: it needs the company's RUC, a loaded
        # certificate, the invoice XML version and a street on the journal's
        # emission address. That is a property of the documents these tests
        # collect, not of the collector, so it is set up once here.
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
        cls.journal_sale_withhold = cls.chart_template.ref("sale_withhold_ec")
        cls.tax_vat12 = cls.chart_template.ref("tax_vat_510_sup_01")
        cls.tax_zero_vat = cls.env["account.tax"].search(
            [("tax_group_id.l10n_ec_type", "=", "zero_vat")], limit=1
        )
        cls.tax_not_charged_vat = cls.env["account.tax"].search(
            [("tax_group_id.l10n_ec_type", "=", "not_charged_vat")], limit=1
        )
        cls.tax_exempt_vat = cls.env["account.tax"].search(
            [("tax_group_id.l10n_ec_type", "=", "exempt_vat")], limit=1
        )
        cls.tax_sale_withhold_vat_100 = cls.chart_template.ref(
            "tax_sale_withhold_vat_100"
        )
        cls.tax_sale_withhold_income = cls.chart_template.ref(
            "tax_withhold_profit_sale_2x100"
        )
        cls.tax_purchase_withhold_vat_100 = cls.chart_template.ref(
            "tax_withhold_vat_100"
        )

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
        because a document is filed under the establishment its journal
        declared.

        Why not the journal sequence: ``l10n_latam_invoice_document`` declares
        ``_unique_name`` over ``(name, journal_id)`` for every posted move, so
        two documents sharing a name in one journal collide. A sequence would
        dodge that, but it cannot be written down, and these tests are
        arithmetic on ``secuencial``.

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

    def _catalog_codes(self, table_code, when):
        """``Tabla`` codes in force on ``when``, read from the catalog.

        ``filtered`` rather than a chained ``search``: ``BaseModel.search`` is
        ``@api.model``, so searching on a recordset ignores that recordset.
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

    def _second_ruc_client(self):
        """A second client carrying the *same* identification type.

        Same ``tpIdCliente``, different ``idCliente`` -- so a row split between
        them can only come from the client, never from a coincidence in the
        identification code.
        """
        return self.env["res.partner"].create(
            {
                "name": "Otro Cliente RUC",
                "vat": "1713109678001",
                "l10n_latam_identification_type_id": self.env.ref("l10n_ec.ec_ruc").id,
                "country_id": self.env.ref("base.ec").id,
            }
        )

    def _document_type(self, value):
        """A document type given either as an xmlid or as a record."""
        return self.env.ref(value) if isinstance(value, str) else value

    def _create_sale(
        self,
        *,
        partner=None,
        taxes=None,
        document_number=None,
        document_type="l10n_ec.ec_dt_01",
        sri_payment="l10n_ec.P1",
        posting_date=PERIOD[0],
        journal=None,
        with_sections=False,
    ):
        """Post one customer invoice carrying every ``ventas`` field a row needs.

        Built through the shared ``_l10n_ec_create_form_move`` fixture rather
        than by hand: that is the path every sibling EDI test drives a sale
        through, and re-deriving it here would only diverge from what the
        addons already prove works.

        ``date`` and ``invoice_date`` are set **before** posting because both
        are readonly on a posted move, and the tests need a 2016 window to prove
        the catalogues are resolved for the reported period rather than for
        today.

        ``document_number`` defaults to ``None``, which means the next number
        from :meth:`_next_document_number` rather than whatever the journal
        sequence happened to be at. A test that needs an exact sequential
        passes it and that value wins.

        The number is written on the **saved record**, not on the form, and that
        is forced rather than chosen: ``account_move_view.xml`` hides
        ``l10n_latam_document_number`` once the journal has a ``highest_name``,
        so a second ``Form`` in the same test refuses the assignment outright.
        Writing the record is also the honest order -- ``name`` is readonly on
        the form once the journal uses documents.
        """
        latam_type = self._document_type(document_type)
        issuing_journal = journal or self.journal_sale
        form = self._l10n_ec_create_form_move(
            move_type="out_invoice",
            internal_type="invoice",
            partner=partner or self.partner_ruc,
            taxes=taxes,
            journal=issuing_journal,
            latam_document_type=latam_type,
            use_payment_term=False,
        )
        if with_sections:
            with form.invoice_line_ids.new() as section:
                section.display_type = "line_section"
                section.name = "SECTION TEST"
            with form.invoice_line_ids.new() as note:
                note.display_type = "line_note"
                note.name = "NOTE TEST"
        invoice = form.save()
        if document_type and not invoice.l10n_latam_document_type_id:
            # A journal that does not use documents leaves the type off the form
            # entirely, because ``_l10n_ec_create_form_move`` only sets it on such
            # a journal. A physical document still has a ``tipoComprobante``.
            invoice.l10n_latam_document_type_id = latam_type.id
        invoice.write(
            {
                "l10n_latam_document_number": document_number
                or self._next_document_number(issuing_journal)
            }
        )
        invoice.write(
            {
                "date": posting_date,
                "invoice_date": posting_date,
                "l10n_ec_sri_payment_id": self.env.ref(sri_payment).id,
            }
        )
        invoice.action_post()
        return invoice

    def _create_credit_note(self, *, partner=None, taxes=None, posting_date=PERIOD[0]):
        """A posted ``out_refund`` carrying the sign Odoo gives a reversal.

        Posted with the signs a customer invoice has and then retyped, which is
        the only way to reach the state ATS has to cope with -- the same shape
        the ``compras`` suite builds. What matters for ``ventas`` is that the
        amounts read back negative, so a collector that reported them verbatim
        would emit a document ``monedaType`` rejects.
        """
        note = self._create_sale(
            partner=partner, taxes=taxes, posting_date=posting_date
        )
        note.write(
            {
                "move_type": "out_refund",
                "l10n_latam_document_type_id": self.env.ref("l10n_ec.ec_dt_04").id,
            }
        )
        self.assertEqual(note.move_type, "out_refund")
        self.assertLess(note.amount_untaxed, 0.0)
        return note

    def _setup_company_for_withholding(self):
        """Give the company what the withholding journal validates against.

        The withholding journal posts through the SRI EDI format, so it needs
        the company's RUC, a loaded certificate and a street on its emission
        address. Set up directly rather than through ``_setup_edi_company_ec``,
        which also rewrites the sales and vendor-bill journals.
        """
        self._setup_company_ec()
        self.certificate.action_validate_and_load()
        self.company.write(
            {
                "l10n_ec_type_environment": "test",
                "l10n_ec_key_type_id": self.certificate.id,
                "l10n_ec_invoice_version": "1.1.0",
            }
        )
        self.journal_sale_withhold.l10n_ec_emission_address_id = self.partner_contact.id

    def _create_withholding(self, invoice, tax, withholding_type="sale"):
        """Post a withholding against ``invoice`` and link the two.

        Built directly rather than through the withholding wizards. The line
        values mirror what those wizards produce, because those are the shapes
        the collector reads. What is skipped is the reconciliation against the
        invoice's receivable line: settling the withholding is an accounting
        concern the collector has no opinion about, and driving it here would
        only couple these tests to reconciliation rules that belong to the
        withholding addon's own suite.

        ``l10n_ec_invoice_withhold_id`` on the basis line is the only link the
        collector follows, and the basis is the value a wizard would compute:
        the invoice's own tax for a VAT withholding, its untaxed amount for an
        income one.

        ``ref`` is the withholding's own number, and it is made unique per call
        because ``l10n_ec_withhold`` constrains a sale withholding to one number
        per client -- a real restriction, not a test artefact, so two withholdings
        for the same client are two different certificates.
        """
        self._setup_company_for_withholding()
        self._withholding_seq = getattr(self, "_withholding_seq", 0) + 1
        if "purchase" in tax.tax_group_id.l10n_ec_type:
            base = abs(invoice.amount_tax_signed)
        else:
            base = abs(invoice.amount_untaxed_signed)
        lines = []
        for tax_data in tax.compute_all(base).get("taxes", []):
            amount = abs(tax_data.get("base"))
            lines.append(
                (
                    0,
                    0,
                    {
                        "partner_id": invoice.partner_id.id,
                        "quantity": 1.0,
                        "price_unit": amount,
                        "account_id": tax_data.get("account_id"),
                        "name": "RET sale basis",
                        "debit": amount,
                        "credit": 0.0,
                        "tax_ids": [(6, 0, tax.ids)],
                        "display_type": "product",
                        "l10n_ec_invoice_withhold_id": invoice.id,
                    },
                )
            )
            lines.append(
                (
                    0,
                    0,
                    {
                        "partner_id": invoice.partner_id.id,
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
                "journal_id": self.journal_sale_withhold.id,
                "date": invoice.date,
                "move_type": "entry",
                "partner_id": invoice.partner_id.id,
                "ref": f"RET-SALE-TEST-{self._withholding_seq:04d}",
                "l10n_latam_document_type_id": self.env.ref("l10n_ec.ec_dt_07").id,
                "l10n_ec_withholding_type": withholding_type,
                "line_ids": lines,
            }
        )
        withholding._post()
        invoice.l10n_ec_withhold_ids = [(4, withholding.id)]
        return withholding

    def _physical_journal(self):
        """A sale journal that does not issue documents.

        A company that still invoices on paper has journals like this one. The
        signal it carries is what ``tipoEmision`` reads: no documents means
        physical issuance.
        """
        return self.journal_sale.copy(
            {"l10n_latam_use_documents": False, "code": "SAL2"}
        )

    def _collect(self, period=PERIOD, **kwargs):
        return self.Collector.collect_ventas_with_errors(
            self.company, period[0], period[1], **kwargs
        )

    def _only_row(self, period=PERIOD):
        rows, errors = self._collect(period=period)
        self.assertFalse(errors, errors)
        self.assertEqual(len(rows), 1, rows)
        return rows[0]

    # ------------------------------------------------------------------
    # The fixture numbers its own documents
    # ------------------------------------------------------------------

    def test_the_sale_fixture_gives_every_document_a_number_of_its_own(self):
        """A name of its own, and a way to ask for one.

        ``l10n_latam_invoice_document`` declares ``_unique_name`` over
        ``(name, journal_id)`` for every posted move, so two documents sharing
        a name in one journal collide -- and this collector derives
        ``secuencial`` from ``name``, so a duplicate would file the wrong
        document number. The ``document_number`` argument is what lets a test
        that needs an exact sequential ask for one instead of reading back
        whatever came.
        """
        explicit = self._create_sale(document_number="001-001-000000900")
        self.assertEqual(explicit.l10n_latam_document_number, "001-001-000000900")
        first = self._create_sale()
        second = self._create_sale()
        self.assertEqual(first.l10n_latam_document_number, "001-001-000000001")
        self.assertEqual(second.l10n_latam_document_number, "001-001-000000002")

    # ------------------------------------------------------------------
    # Aggregation: the whole point of this block
    # ------------------------------------------------------------------

    def test_01_two_documents_for_one_client_and_type_make_one_row(self):
        """§5.4: ``ventas`` is aggregated; ``compras`` is not."""
        first = self._create_sale(taxes=self.tax_vat12)
        second = self._create_sale(taxes=self.tax_vat12)
        rows, errors = self._collect()
        self.assertFalse(errors, errors)
        self.assertEqual(len(rows), 1, "two documents must fold into one row")
        row = rows[0]
        self.assertEqual(row["numeroComprobantes"], 2)
        self.assertEqual(
            row["baseImpGrav"], first.amount_untaxed + second.amount_untaxed
        )
        self.assertEqual(row["montoIva"], first.amount_tax + second.amount_tax)

    def test_02_a_folded_row_carries_the_full_primary_key(self):
        self._create_sale(taxes=self.tax_vat12)
        self._create_sale(taxes=self.tax_vat12)
        row = self._only_row()
        self.assertEqual(row["tpIdCliente"], "04")
        self.assertEqual(row["idCliente"], self.partner_ruc.vat)
        self.assertEqual(row["tipoComprobante"], "01")

    def test_03_two_clients_make_two_rows(self):
        other = self._second_ruc_client()
        self._create_sale(partner=self.partner_ruc)
        self._create_sale(partner=other)
        rows, errors = self._collect()
        self.assertFalse(errors, errors)
        self.assertEqual(len(rows), 2)
        # Same identification *type*, different identification: the split can
        # only come from the client.
        self.assertEqual({row["tpIdCliente"] for row in rows}, {"04"})
        self.assertEqual(
            sorted(row["idCliente"] for row in rows),
            sorted([self.partner_ruc.vat, other.vat]),
        )

    def test_04_two_document_types_make_two_rows(self):
        self._create_sale(taxes=self.tax_vat12, document_type="l10n_ec.ec_dt_01")
        self._create_sale(taxes=self.tax_vat12, document_type="l10n_ec.ec_dt_02")
        rows, errors = self._collect()
        self.assertFalse(errors, errors)
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["tipoComprobante"] for row in rows}, {"01", "02"})
        self.assertEqual({row["numeroComprobantes"] for row in rows}, {1})

    def test_05_a_three_document_group_counts_three(self):
        for _ in range(3):
            self._create_sale(taxes=self.tax_vat12)
        row = self._only_row()
        self.assertEqual(row["numeroComprobantes"], 3)

    # ------------------------------------------------------------------
    # Sales returns: absolute amounts under their own document type
    # ------------------------------------------------------------------

    def test_06_a_credit_note_is_filed_under_type_04_with_positive_amounts(self):
        """``monedaType`` has ``minInclusive 0.0``; the document type carries the
        sign.

        ``detalleVentasType`` has no element that could express a reversal other
        than by its ``tipoComprobante``, so a credit note is a row whose
        ``tipoComprobante`` is ``04`` and whose amounts are magnitudes. Negating
        them would produce a document the schema rejects outright.
        """
        note = self._create_credit_note(taxes=self.tax_vat12)
        rows, errors = self._collect()
        self.assertFalse(errors, errors)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["tipoComprobante"], "04")
        self.assertEqual(row["numeroComprobantes"], 1)
        self.assertEqual(row["baseImpGrav"], abs(note.amount_untaxed))
        self.assertEqual(row["montoIva"], abs(note.amount_tax))
        for field, value in row.items():
            if isinstance(value, float):
                self.assertGreaterEqual(value, 0.0, field)

    def test_07_a_credit_note_and_its_invoice_are_two_rows(self):
        self._create_sale(taxes=self.tax_vat12)
        self._create_credit_note(taxes=self.tax_vat12)
        rows, errors = self._collect()
        self.assertFalse(errors, errors)
        self.assertEqual(len(rows), 2)
        by_type = {row["tipoComprobante"]: row for row in rows}
        self.assertEqual(by_type["04"]["numeroComprobantes"], 1)
        self.assertEqual(by_type["01"]["numeroComprobantes"], 1)
        # Both rows report magnitudes: the reversal is separated by its document
        # type, not by the sign of its amounts.
        self.assertGreater(by_type["04"]["baseImpGrav"], 0.0)
        self.assertGreater(by_type["01"]["baseImpGrav"], 0.0)
        self.assertNotIn("formasDePago", by_type["04"])
        self.assertIn("formasDePago", by_type["01"])

    def test_08_a_credit_note_does_not_carry_a_payment_form(self):
        """The catalog states ``formaPago`` "no aplica para los tipos de
        comprobantes Notas de Crédito (04)"."""
        self._create_credit_note(taxes=self.tax_vat12)
        row = self._only_row()
        self.assertNotIn("formasDePago", row)

    def test_09_two_credit_notes_for_one_client_fold_into_their_own_row(self):
        first = self._create_credit_note(taxes=self.tax_vat12)
        second = self._create_credit_note(taxes=self.tax_vat12)
        row = self._only_row()
        self.assertEqual(row["tipoComprobante"], "04")
        self.assertEqual(row["numeroComprobantes"], 2)
        self.assertEqual(
            row["baseImpGrav"], abs(first.amount_untaxed) + abs(second.amount_untaxed)
        )

    # ------------------------------------------------------------------
    # tipoEmision: derived from a record, and part of the key
    # ------------------------------------------------------------------

    def test_10_tipo_emision_resolves_from_the_journal_through_tabla_20(self):
        """The ficha: one character, physical or electronic, ``Tabla 20``.

        The signal is a record, not a flag invented here -- the issuing
        journal's own ``l10n_latam_use_documents``, the field core ``l10n_ec``
        itself computes ``l10n_ec_require_emission`` from. The code that reaches
        the file is the catalogue's.
        """
        self.assertTrue(self.journal_sale.l10n_latam_use_documents)
        self.assertTrue(self.journal_sale.l10n_ec_require_emission)
        invoice = self._create_sale(taxes=self.tax_vat12)
        self.assertEqual(invoice.journal_id, self.journal_sale)
        row = self._only_row()
        electronic = self._catalog_codes("20", PERIOD[0])
        self.assertIn(row["tipoEmision"], electronic)
        self.assertEqual(row["tipoEmision"], "E")

    def test_11_a_journal_that_does_not_use_documents_files_physical(self):
        """Same client, same document type, a journal without documents.

        The ficha is explicit that the same document type may be filed again for
        the same client in the same period *provided the emission type differs*:
        "se puede ingresar el mismo tipo de documento siempre que difiera de la
        emisión de un mismo cliente en el período informado". Two documents that
        differ only in emission type are therefore two rows, not one row with an
        ambiguous ``tipoEmision``.
        """
        physical_journal = self._physical_journal()
        self.assertFalse(physical_journal.l10n_latam_use_documents)
        self._create_sale(taxes=self.tax_vat12)
        self._create_sale(taxes=self.tax_vat12, journal=physical_journal)
        rows, errors = self._collect()
        self.assertFalse(errors, errors)
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["tipoComprobante"] for row in rows}, {"01"})
        self.assertEqual({row["tipoEmision"] for row in rows}, {"E", "F"})
        for row in rows:
            self.assertEqual(row["numeroComprobantes"], 1)

    def test_12_tipo_emision_outside_the_reported_period_blocks(self):
        """``Tabla 20`` publishes the electronic code from 2016-01-01.

        A 2015-12 report of an electronically issued document must be refused:
        the code the journal implies did not exist on that day, so the only
        honest answer is none.
        """
        self.assertEqual(self._catalog_codes("20", BEFORE_ELECTRONIC_PERIOD[0]), ["F"])
        self.assertIn("E", self._catalog_codes("20", PERIOD[0]))
        self._create_sale(
            taxes=self.tax_vat12, posting_date=BEFORE_ELECTRONIC_PERIOD[0]
        )
        rows, errors = self._collect(period=BEFORE_ELECTRONIC_PERIOD)
        self.assertEqual(rows, [])
        self.assertEqual([error["field"] for error in errors], ["tipoEmision"])
        # The message names what *is* in force that day, read from the catalogue.
        message = str(errors[0]["message"])
        self.assertIn("F", message)

    def test_13_the_emission_keyword_matches_exactly_one_tabla_20_row(self):
        """Pin the description keywords against the catalogue itself.

        They are descriptions, not codes: the code emitted is always the
        catalogue row's own. If the SRI ever published a third emission type,
        one keyword would stop selecting exactly one row and this fails rather
        than filing an arbitrary emission type.
        """
        from ..models.l10n_ec_ats_collector import TABLA_20_KEYWORD_BY_USES_DOCUMENTS

        self.assertEqual(len(TABLA_20_KEYWORD_BY_USES_DOCUMENTS), 2)
        for uses_documents, keyword in TABLA_20_KEYWORD_BY_USES_DOCUMENTS.items():
            matching = [
                entry
                for entry in self.CatalogEntry._applicable_on(PERIOD[0])
                if entry.table_id.code == "20"
                and self.Collector._l10n_ec_description_contains(entry, keyword)
            ]
            self.assertEqual(len(matching), 1, (uses_documents, keyword, matching))
            self.assertEqual(
                self.Collector._l10n_ec_tipo_emision(
                    self._create_sale(
                        taxes=self.tax_vat12,
                        journal=self.journal_sale
                        if uses_documents
                        else self._physical_journal(),
                    ),
                    PERIOD[0],
                    lambda *_: None,
                ),
                matching[0].code,
            )

    # ------------------------------------------------------------------
    # Bases
    # ------------------------------------------------------------------

    def test_14_a_gravated_sale_lands_its_base_in_base_imp_grav(self):
        invoice = self._create_sale(taxes=self.tax_vat12)
        row = self._only_row()
        self.assertEqual(row["baseImpGrav"], invoice.amount_untaxed)
        self.assertEqual(row["montoIva"], invoice.amount_tax)
        self.assertEqual(row["baseNoGraIva"], 0.0)
        self.assertEqual(row["baseImponible"], 0.0)
        self.assertEqual(row["montoIce"], 0.0)

    def test_15_the_other_buckets_are_read_from_their_own_groups(self):
        """``not_charged_vat`` and ``zero_vat`` are distinct selections."""
        self._create_sale(taxes=self.tax_not_charged_vat)
        self._create_sale(taxes=self.tax_zero_vat)
        rows, errors = self._collect()
        self.assertFalse(errors, errors)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertGreater(row["baseNoGraIva"], 0.0)
        self.assertGreater(row["baseImponible"], 0.0)
        self.assertEqual(row["baseImpGrav"], 0.0)

    def test_16_the_row_has_no_exempt_base(self):
        """``detalleVentasType`` has no ``baseImpExe``; ``detalleComprasType``
        does. The XSD is what decides, not a habit carried across blocks."""
        self._create_sale(taxes=self.tax_exempt_vat)
        row = self._only_row()
        self.assertNotIn("baseImpExe", row)
        # An exempt-only sale therefore reports every base at zero rather than
        # inventing a bucket the schema has no element for.
        self.assertEqual(row["baseNoGraIva"], 0.0)
        self.assertEqual(row["baseImponible"], 0.0)
        self.assertEqual(row["baseImpGrav"], 0.0)

    def test_17_section_and_note_lines_contribute_nothing(self):
        invoice = self._create_sale(taxes=self.tax_vat12, with_sections=True)
        row = self._only_row()
        self.assertEqual(row["baseImpGrav"], invoice.amount_untaxed)

    def test_18_draft_and_out_of_window_sales_are_not_collected(self):
        posted = self._create_sale(taxes=self.tax_vat12)
        draft = self._create_sale(taxes=self.tax_vat12)
        draft.button_draft()
        other_month = self._create_sale(
            taxes=self.tax_vat12, posting_date=date(2016, 5, 10)
        )
        self.assertEqual(posted.state, "posted")
        self.assertEqual(draft.state, "draft")
        self.assertNotEqual(other_month.date, posted.date)
        row = self._only_row()
        self.assertEqual(row["numeroComprobantes"], 1)

    def test_19_an_empty_period_yields_an_empty_list_and_no_error(self):
        """No sales is a legitimate report, not a failure."""
        rows, errors = self._collect(period=EMPTY_PERIOD)
        self.assertEqual(rows, [])
        self.assertEqual(errors, [])
        self.assertEqual(
            self.Collector.collect_ventas(
                self.company, EMPTY_PERIOD[0], EMPTY_PERIOD[1]
            ),
            [],
        )

    # ------------------------------------------------------------------
    # parteRelVtas
    # ------------------------------------------------------------------

    def test_20_parte_rel_vtas_follows_the_related_party_flag(self):
        self.partner_ruc.l10n_ec_related_party = False
        self._create_sale(taxes=self.tax_vat12)
        self.assertEqual(self._only_row()["parteRelVtas"], "NO")

        self.partner_ruc.l10n_ec_related_party = True
        self.assertEqual(self._only_row()["parteRelVtas"], "SI")

    def test_21_the_final_consumer_carries_no_related_party_flag(self):
        """The ficha displays ``parteRel`` only for identification types 04, 05
        and 06 -- not for the consumer sentinel, which is ``07``.

        ``ats.xsd`` makes the element optional, so omitting it is what the
        schema expects and what the ficha asks for. Accepting the sentinel as a
        client is the opposite of ATS-06's purchase rule and equally deliberate:
        on the sales side ``Tabla 2`` publishes it as a transaction-type-2 code.
        """
        self._create_sale(partner=self.partner_cf, taxes=self.tax_vat12)
        row = self._only_row()
        self.assertEqual(row["tpIdCliente"], "07")
        self.assertEqual(row["idCliente"], self.partner_cf.vat)
        self.assertNotIn("parteRelVtas", row)

    # ------------------------------------------------------------------
    # Retentions we issued
    # ------------------------------------------------------------------

    def test_22_valor_ret_iva_comes_from_the_sale_side_withholding(self):
        invoice = self._create_sale(taxes=self.tax_vat12)
        self._create_withholding(invoice, self.tax_sale_withhold_vat_100)
        row = self._only_row()
        withheld = invoice.l10n_ec_withhold_ids.line_ids.filtered(
            lambda line: line.display_type == "product"
        )
        expected = sum(abs(line.l10n_ec_withhold_tax_amount) for line in withheld)
        self.assertGreater(expected, 0.0)
        self.assertEqual(row["valorRetIva"], expected)

    def test_23_valor_ret_renta_comes_from_the_sale_side_withholding(self):
        invoice = self._create_sale(taxes=self.tax_vat12)
        self._create_withholding(invoice, self.tax_sale_withhold_income)
        row = self._only_row()
        withheld = invoice.l10n_ec_withhold_ids.line_ids.filtered(
            lambda line: line.display_type == "product"
        )
        expected = sum(abs(line.l10n_ec_withhold_tax_amount) for line in withheld)
        self.assertGreater(expected, 0.0)
        self.assertEqual(row["valorRetRenta"], expected)
        self.assertEqual(row["valorRetIva"], 0.0)

    def test_24_a_purchase_side_withholding_never_reaches_a_sales_row(self):
        """``valorRetIva`` is what *the client* withheld from us.

        The purchase withholding is attached to the same invoice and carries the
        mirror-image tax group, which is exactly the pair a collector that only
        looked at the linked line would add up.
        """
        invoice = self._create_sale(taxes=self.tax_vat12)
        self._create_withholding(
            invoice, self.tax_purchase_withhold_vat_100, withholding_type="purchase"
        )
        row = self._only_row()
        self.assertEqual(row["valorRetIva"], 0.0)
        self.assertEqual(row["valorRetRenta"], 0.0)

    def test_25_both_sale_side_retentions_reach_the_same_row(self):
        invoice = self._create_sale(taxes=self.tax_vat12)
        self._create_withholding(invoice, self.tax_sale_withhold_vat_100)
        self._create_withholding(invoice, self.tax_sale_withhold_income)
        row = self._only_row()
        self.assertGreater(row["valorRetIva"], 0.0)
        self.assertGreater(row["valorRetRenta"], 0.0)

    def test_26_retentions_are_folded_across_the_whole_group(self):
        """Two documents, one row: the retentions are the client's totals."""
        first = self._create_sale(taxes=self.tax_vat12)
        second = self._create_sale(taxes=self.tax_vat12)
        self._create_withholding(first, self.tax_sale_withhold_vat_100)
        self._create_withholding(second, self.tax_sale_withhold_vat_100)
        row = self._only_row()
        self.assertEqual(row["numeroComprobantes"], 2)
        expected = sum(
            abs(line.l10n_ec_withhold_tax_amount)
            for line in (first | second).l10n_ec_withhold_ids.line_ids
            if line.display_type == "product"
        )
        self.assertEqual(row["valorRetIva"], expected)

    def test_27_both_retentions_are_mandatory_and_zero_without_a_withholding(self):
        """The ficha marks both obligatorio; ``ats.xsd`` agrees for ``ventas``.

        Zero is a sourced amount here, not a substituted one: the client
        withheld nothing.
        """
        self._create_sale(taxes=self.tax_vat12)
        row = self._only_row()
        self.assertEqual(row["valorRetIva"], 0.0)
        self.assertEqual(row["valorRetRenta"], 0.0)

    def test_27b_a_iva_withholding_rate_tabla_11_never_published_blocks(self):
        """A VAT-withholding tax *is* its rate, so the rate has to be a rate
        ``Tabla 11`` publishes on the reported day.

        The chart template's sale-side VAT withholdings are exactly the six
        published rates, so one is re-rated here. Without the check the amount
        would be filed against a rate the SRI has no element for.
        """
        published = {
            entry.percentage
            for entry in self.CatalogEntry._applicable_on(PERIOD[0])
            if entry.table_id.code == "11"
        }
        self.assertTrue(published)
        unpublished = self.tax_sale_withhold_vat_100.copy(
            {"name": f"{self.tax_sale_withhold_vat_100.name} 5", "amount": 5.0}
        )
        self.assertNotIn(5.0, published)
        self.assertEqual(unpublished.tax_group_id.l10n_ec_type, "withhold_vat_sale")
        invoice = self._create_sale(taxes=self.tax_vat12)
        self._create_withholding(invoice, unpublished)
        rows, errors = self._collect()
        self.assertEqual(rows, [])
        self.assertEqual([error["field"] for error in errors], ["valorRetIva"])
        self.assertIn("5", str(errors[0]["message"]))

    # ------------------------------------------------------------------
    # Blocking conditions
    # ------------------------------------------------------------------

    def test_28_a_client_without_identification_blocks(self):
        """The SRI EDI format refuses to post a sale whose client has no
        identification, so the collector's own guard is reached the other way
        round: the identification is removed **after** posting, which is what a
        corrected or deleted partner record looks like to a period that is
        filed later. A row whose ``idCliente`` could not be sourced would put an
        empty client in a filed return."""
        invoice = self._create_sale(taxes=self.tax_vat12)
        invoice.partner_id.vat = False
        rows, errors = self._collect()
        self.assertEqual(rows, [])
        self.assertIn("tpIdCliente", [error["field"] for error in errors])
        self.assertNotIn("idCliente", str(rows))

    def test_29_an_all_zero_identification_blocks(self):
        """``0000000000000`` is not an identification of anybody.

        The partner keeps its identification *type*, so the collector can
        derive ``tpIdCliente`` from it, and the placeholder is caught where it
        belongs: in the identification itself.
        """
        partner = self.env["res.partner"].create(
            {
                "name": "Cliente Placeholder",
                "vat": "0000000000000",
                "l10n_latam_identification_type_id": self.env.ref("l10n_ec.ec_ruc").id,
                "country_id": self.env.ref("base.ec").id,
            }
        )
        self._create_sale(partner=partner, taxes=self.tax_vat12)
        rows, errors = self._collect()
        self.assertEqual(rows, [])
        self.assertIn("idCliente", [error["field"] for error in errors])

    def test_30_a_sale_without_a_document_type_blocks(self):
        """A journal that does not use documents does not demand one.

        That is the one way to reach a posted sale with no ``tipoComprobante``,
        and it is a real state: a company that still invoices on paper. ``Tabla
        4`` requires the code regardless, so the collector refuses rather than
        filing the row without it.
        """
        invoice = self._create_sale(
            taxes=self.tax_vat12,
            document_type=False,
            journal=self._physical_journal(),
        )
        self.assertFalse(invoice.l10n_latam_document_type_id)
        self.assertEqual(invoice.state, "posted")
        rows, errors = self._collect()
        self.assertEqual(rows, [])
        self.assertIn("tipoComprobante", [error["field"] for error in errors])

    def test_31_a_document_type_outside_tabla_4_blocks(self):
        """A code the SRI never published must not reach the return.

        Every document type the EC localization ships *is* a ``Tabla 4`` code, and
        a draft cannot be given one that is not: the field is computed from the
        types the localization allows and resets itself. So the code is changed on
        the document type **after** posting, which is what a catalogue row that
        was retired or a mis-keyed record looks like by filing time. What the
        collector files is the document type's own code, so an unknown one has no
        place in a filed return.
        """
        self.assertNotIn("99", self._catalog_codes("04", PERIOD[0]))
        invoice = self._create_sale(taxes=self.tax_vat12)
        document_type = invoice.l10n_latam_document_type_id
        document_type.code = "99"
        self.assertEqual(invoice.l10n_latam_document_type_id.code, "99")
        rows, errors = self._collect()
        self.assertEqual(rows, [])
        self.assertEqual([error["field"] for error in errors], ["tipoComprobante"])
        self.assertIn("99", str(errors[0]["message"]))

    def test_32_a_document_type_outside_the_reported_period_blocks(self):
        """The regression guard for the chained-search defect.

        ``BaseModel.search`` is ``@api.model``, so searching on a recordset
        ignores that recordset. A collector that filtered its temporal read by
        chaining a ``search`` onto the result would hand back every era at once
        and this document would be filed in a period the SRI never published it
        for. ``Tabla 4`` stores no ``Fecha de vigencia`` of its own -- the sheet
        spells that column ``vacío`` in all forty rows -- so the window is set
        here to the one the SRI's own history would give the row: in force from
        2020, absent before it.
        """
        entry = self._catalog_entry("04", "18")
        self.assertTrue(entry)
        entry.date_start = date(2020, 1, 1)
        self.assertIn("18", self._catalog_codes("04", MODERN_PERIOD[0]))
        self.assertNotIn("18", self._catalog_codes("04", PERIOD[0]))

        self._create_sale(taxes=self.tax_vat12, document_type="l10n_ec.ec_dt_18")
        rows, errors = self._collect()
        self.assertEqual(rows, [])
        self.assertEqual([error["field"] for error in errors], ["tipoComprobante"])
        message = str(errors[0]["message"])
        self.assertIn("18", message)

    def test_32b_the_same_document_type_is_accepted_for_a_period_that_covers_it(self):
        entry = self._catalog_entry("04", "18")
        entry.date_start = date(2020, 1, 1)
        self._create_sale(
            taxes=self.tax_vat12,
            document_type="l10n_ec.ec_dt_18",
            posting_date=MODERN_PERIOD[0],
        )
        row = self._only_row(period=MODERN_PERIOD)
        self.assertEqual(row["tipoComprobante"], "18")

    def test_33_forma_de_pago_resolves_through_tabla_13(self):
        invoice = self._create_sale(taxes=self.tax_vat12)
        row = self._only_row()
        payment_code = invoice.l10n_ec_sri_payment_id.code
        self.assertIn(payment_code, self._catalog_codes("13", PERIOD[0]))
        self.assertEqual(row["formasDePago"], [{"formaPago": payment_code}])

    def test_34_forma_de_pago_outside_tabla_13_for_the_period_blocks(self):
        """``P16`` is a real ``Tabla 13`` code, in force from 2016-05-01.

        Reporting 2016-03 must reject it, and the message has to name the codes
        that *are* valid that month -- read from the catalogue, not from a
        Python literal.
        """
        valid_2016 = self._catalog_codes("13", PERIOD[0])
        self.assertNotIn("16", valid_2016)
        self.assertIn("01", valid_2016)
        self._create_sale(taxes=self.tax_vat12, sri_payment="l10n_ec.P16")
        rows, errors = self._collect()
        self.assertEqual(rows, [])
        self.assertEqual([error["field"] for error in errors], ["formasDePago"])
        message = str(errors[0]["message"])
        self.assertIn("16", message)
        for code in valid_2016:
            self.assertIn(code, message)

    def test_35_the_same_payment_form_is_accepted_for_a_period_that_covers_it(self):
        """``Tabla 13`` publishes code ``16`` from 2016-05-01, so the very same
        sale that :meth:`test_34` refuses for March is filed for June."""
        self.assertIn("16", self._catalog_codes("13", DEBIT_CARD_PERIOD[0]))
        self._create_sale(
            taxes=self.tax_vat12,
            sri_payment="l10n_ec.P16",
            posting_date=DEBIT_CARD_PERIOD[0],
        )
        row = self._only_row(period=DEBIT_CARD_PERIOD)
        self.assertEqual(row["formasDePago"], [{"formaPago": "16"}])

    def test_36_a_broken_member_blocks_the_whole_group(self):
        """An aggregated row cannot be half-reported.

        One unusable document out of two means the sums would describe a set the
        company never had, so the whole row is withheld and both documents are
        named.
        """
        self._create_sale(taxes=self.tax_vat12)
        second = self._create_sale(taxes=self.tax_vat12)
        second.l10n_ec_sri_payment_id = self.env.ref("l10n_ec.P16").id
        rows, errors = self._collect()
        self.assertEqual(rows, [])
        self.assertEqual([error["field"] for error in errors], ["formasDePago"])
        self.assertNotIn("numeroComprobantes", str(rows))

    def test_37_fecha_registro_outside_the_reported_month_blocks(self):
        self._create_sale(taxes=self.tax_vat12, posting_date=date(2016, 2, 15))
        rows, errors = self._collect(period=(date(2016, 1, 1), date(2016, 3, 31)))
        self.assertEqual(rows, [])
        self.assertEqual([error["field"] for error in errors], ["fechaRegistro"])

    def test_37b_a_vendor_bill_is_not_a_sale(self):
        """``ventas`` and ``compras`` read the same records and must not cross.

        A bill posted in the same period, on the same accounting date and for the
        same client-side amounts, belongs to the purchase block only. The
        selection is what keeps them apart, so both blocks are read here.
        """
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
        # ``_post`` refuses a purchase document with no tax support.
        bill.l10n_ec_tax_support = "01"
        bill.l10n_ec_authorization_number = "123456789012"
        bill.action_post()

        self._create_sale(taxes=self.tax_vat12)
        rows, errors = self._collect()
        self.assertFalse(errors, errors)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["numeroComprobantes"], 1)
        # And the purchase block sees only the bill.
        purchase_rows, purchase_errors = self.Collector.collect_compras_with_errors(
            self.company, PERIOD[0], PERIOD[1]
        )
        self.assertFalse(purchase_errors, purchase_errors)
        self.assertEqual(len(purchase_rows), 1)
        self.assertEqual(purchase_rows[0]["idProv"], self.partner_ruc.vat)

    # ------------------------------------------------------------------
    # Row shape
    # ------------------------------------------------------------------

    def test_38_the_row_keys_are_exactly_the_ats_element_names(self):
        """ATS-10 is a straight mapping, so the keys must be the XSD names."""
        invoice = self._create_sale(taxes=self.tax_vat12)
        self._create_withholding(invoice, self.tax_sale_withhold_vat_100)
        row = self._only_row()
        self.assertEqual(
            set(row),
            {
                "tpIdCliente",
                "idCliente",
                "parteRelVtas",
                "tipoComprobante",
                "tipoEmision",
                "numeroComprobantes",
                "baseNoGraIva",
                "baseImponible",
                "baseImpGrav",
                "montoIva",
                "montoIce",
                "valorRetIva",
                "valorRetRenta",
                "formasDePago",
            },
        )
        # Never the purchase block's elements, and never the establishment
        # block's: ``establecimiento`` and ``puntoEmision`` belong to
        # ``ventasEstablecimiento``.
        for absent in (
            "baseImpExe",
            "establecimiento",
            "puntoEmision",
            "secuencial",
            "codSustento",
            "parteRel",
            "air",
            "compensaciones",
            "codRetAir",
            "porcentajeAir",
            "valRetAir",
        ):
            self.assertNotIn(absent, row)

    def test_39_the_conditional_client_fields_appear_for_a_foreign_client(self):
        """``tipoCliente`` and ``denoCli`` are conditional on the passport
        identification type, exactly as ``tipoProv`` / ``denoProv`` are on the
        purchase side."""
        self._create_sale(partner=self.partner_passport, taxes=self.tax_vat12)
        row = self._only_row()
        self.assertEqual(row["tpIdCliente"], "06")
        self.assertTrue(row["tipoCliente"])
        self.assertTrue(row["denoCli"])
        self.assertEqual(row["parteRelVtas"], "NO")
