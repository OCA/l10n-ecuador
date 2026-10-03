from datetime import date

from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.l10n_ec_account_edi.tests.test_edi_common import TestL10nECEdiCommon

# The same window ATS-07 uses: ``Tabla 20`` publishes the electronic emission
# code from 2016-01-01, ``Tabla 13`` still carries the 2013 payment forms and
# ``Tabla 5`` is at its 2016 state.
PERIOD = (date(2016, 3, 1), date(2016, 3, 31))
MODERN_PERIOD = (date(2026, 3, 1), date(2026, 3, 31))
EMPTY_PERIOD = (date(2016, 7, 1), date(2016, 7, 31))
#: ``Tabla 21`` code ``01`` (Ley Solidaridad) is in force from 2016-06-01 and
#: code ``02`` (Medios Electrónicos) from 2016-05-01, so **neither exists on the
#: day ``PERIOD`` starts**. Read through the temporal mixin rather than against
#: the table, or the omission test below would pass for the wrong reason.
TABLA_21_DATE = date(2016, 7, 1)

#: The three ``ventas`` base buckets ``totalVentas`` is defined as the sum of.
#: Mirrors ``Catalogo_ATS.xls`` / ``ESQUEMA TIPO 1 Y 2`` row 10, which names
#: exactly these three fields and no others.
TOTAL_VENTAS_BUCKETS = ("baseNoGraIva", "baseImponible", "baseImpGrav")


@tagged("post_install_l10n", "post_install", "-at_install")
class TestL10nEcAtsCollectorVentasEstablecimiento(TestL10nECEdiCommon):
    """One ``ventasEstablecimiento`` row per **our own** establishment.

    ``CLAVE PRIMARIA (2)`` row 94 marks ``codEstab`` alone as this block's
    general key component, so the granularity is one row per establishment, not
    per document and not per client. The ficha then ties the row count to a
    header field: *"debe generarse igual número de registros que el valor
    informado en el campo número de establecimientos del sujeto pasivo,
    inscritos en el RUC"*.

    That sentence decides the two questions this suite exists to pin.

    **Which establishments? The one in the RUC, not the ones that sold.**
    ``numEstabRuc`` counts establishments *inscribed in the RUC* -- ficha:
    *"el número total de establecimientos en estado activo que el contribuyente
    posee inscritos en el Registro Único de Contribuyentes"* -- so an
    establishment with no sales in the period still gets a row, at ``0.00``.
    Dropping it would make ``len(rows) != numEstabRuc``, the check the ficha
    states.

    **Is ``ventasEstab`` gross or net? Net.** ``ESQUEMA`` row 103 says the sum
    of those boxes *"debe ser igual al valor neto (se restan los valores de
    NC) de todas las ventas registradas, caso contrario error"*, and the
    ficha's own ceiling -- *"la sumatoria del total de ventas por los
    establecimientos no puede ser mayor al valor registrado en el campo total
    ventas"* -- is only informative if a row can come out **below**
    ``totalVentas``. ``ats.xsd:1464`` closes the argument: ``ventasEstab`` is
    typed ``totalVentasType``, the only amount type in the schema whose
    pattern admits a leading minus, while every ``ventas`` base is
    ``monedaType`` with ``minInclusive 0.0``.

    So ``totalVentas`` stays **gross** -- the sum of the three absolute
    buckets over the ``ventas`` rows, exactly as ``ESQUEMA`` row 10 states --
    and ``totalVentas >= sum(ventasEstab)``, with equality precisely when the
    period holds no credit note. Both halves of that inequality are asserted
    here arithmetically, against fixtures whose figures are known literals,
    rather than by comparing one collector output against another.

    This is also the first place the ``000`` rule of §5.4b agrees with the
    schema: ``ventasEstabType`` (``ats.xsd:1468``) and ``numEstabRucType``
    (``ats.xsd:1482``) both carry ``minExclusive 000``. It still has to be
    enforced here, because ``account.journal`` accepts ``000`` today --
    ``l10n_ec_base/models/account_journal.py:18`` checks only the length and
    ``isnumeric()``, both of which ``"000"`` satisfies.
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
        # version and a street on the journal's emission address. The same setup
        # ATS-07 uses, for the same reason: it is a property of the documents
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
        cls.journal_sale_withhold = cls.chart_template.ref("sale_withhold_ec")
        cls.tax_vat12 = cls.chart_template.ref("tax_vat_510_sup_01")
        cls.tax_zero_vat = cls.env["account.tax"].search(
            [("tax_group_id.l10n_ec_type", "=", "zero_vat")], limit=1
        )
        cls.tax_not_charged_vat = cls.env["account.tax"].search(
            [("tax_group_id.l10n_ec_type", "=", "not_charged_vat")], limit=1
        )
        # Three products at round prices, one per ``totalVentas`` bucket, so the
        # header arithmetic is checkable against a literal rather than against
        # whatever a collector happened to produce.
        cls.product_gravable = cls._priced_product(100.0)
        cls.product_zero = cls._priced_product(200.0)
        cls.product_not_charged = cls._priced_product(300.0)

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
        because this block has **two** derivations of the establishment set --
        the journals' ``l10n_ec_entity`` and the entity segment of the recorded
        document number -- and both have to agree.

        Why not the journal sequence: ``l10n_latam_invoice_document`` declares
        ``_unique_name`` over ``(name, journal_id)`` for every posted move, so
        two documents sharing a name in one journal collide. A sequence would
        dodge that, but it cannot be written down, and ``test_12``/``test_18``
        assert the entity and emission point read back off the document.

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

        Priced explicitly rather than reusing ``product_a``, because the
        assertions below add round numbers across three buckets and an
        arbitrary catalogue price would make that arithmetic unreadable.
        """
        return cls.env["product.product"].create(
            {
                "name": f"ATS Establecimiento {price:.2f}",
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
        ``@api.model``, so searching on a recordset ignores that recordset and
        hands back every era at once. Asserting the catalog's own facts before
        anything derived from them is what keeps that defect visible -- it is
        the guard ATS-06 needed after shipping exactly that bug.
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
        sri_payment="l10n_ec.P1",
        posting_date=PERIOD[0],
        journal=None,
    ):
        """Post one customer invoice, driven through the shared EDI fixture.

        ``_l10n_ec_create_form_move`` is the path every sibling EDI test drives
        a sale through, so it is reused rather than re-derived. ``date`` and
        ``invoice_date`` are set **before** posting because both are readonly on
        a posted move, and the suite needs a 2016 window to prove the catalogs
        are resolved for the reported period rather than for today.

        ``document_number`` defaults to ``None`` -- which means the next number
        from :meth:`_next_document_number`, carrying **this** journal's
        establishment and emission point, rather than whatever the journal
        sequence happened to be at. That matters here more than anywhere else:
        ``codEstab`` is read off the document as well as off the journal, so a
        number naming a different establishment would move the sale into another
        row. A test that needs an exact sequential passes it and that value
        wins.

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
        invoice.write(
            {
                "date": posting_date,
                "invoice_date": posting_date,
                "l10n_ec_sri_payment_id": self.env.ref(sri_payment).id,
            }
        )
        invoice.action_post()
        return invoice

    def _create_credit_note(self, *, taxes=None, products=None, posting_date=PERIOD[0]):
        """A posted ``out_refund`` carrying the sign Odoo gives a reversal.

        Posted with the signs a customer invoice has and then retyped, which is
        the only way to reach the state ATS has to cope with. What matters here
        is that the amounts read back negative, so a collector reporting them
        verbatim into ``ventasEstab`` would double-count a reversal instead of
        cancelling it.
        """
        note = self._create_sale(
            taxes=taxes, products=products, posting_date=posting_date
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

    def _second_sale_journal(self, entity, emission="001", code="SAL2"):
        """A second active sale journal carrying its own ``entity``.

        The EC chart template gives its journals no establishment at all, so a
        second establishment has to be declared rather than discovered.
        ``l10n_ec_entity`` is ``copy=False``, so the value is passed explicitly.
        """
        return self.journal_sale.copy(
            {"l10n_ec_entity": entity, "l10n_ec_emission": emission, "code": code}
        )

    def _collect(self, period=PERIOD):
        return self.Collector.collect_ventas_establecimiento_with_errors(
            self.company, period[0], period[1]
        )

    def _collect_ventas(self, period=PERIOD):
        return self.Collector.collect_ventas_with_errors(
            self.company, period[0], period[1]
        )

    def _header(self, period=PERIOD):
        """The header fields, read from both blocks of the same period."""
        ventas_rows, _ventas_errors = self._collect_ventas(period=period)
        estab_rows, _estab_errors = self._collect(period=period)
        return self.Collector.collect_iva_header_with_errors(ventas_rows, estab_rows)

    def _only_row(self, period=PERIOD):
        rows, errors = self._collect(period=period)
        self.assertFalse(errors, errors)
        self.assertEqual(len(rows), 1, rows)
        return rows[0]

    def _rows_by_establishment(self, period=PERIOD):
        rows, errors = self._collect(period=period)
        self.assertFalse(errors, errors)
        return {row["codEstab"]: row for row in rows}

    # ------------------------------------------------------------------
    # The fixture numbers its own documents
    # ------------------------------------------------------------------

    def test_the_sale_fixture_gives_every_document_a_number_of_its_own(self):
        """A name of its own, a way to ask for one, and the establishment the
        journal declared.

        This block keys on ``codEstab``, which has two derivations: the issuing
        journal's ``l10n_ec_entity``, and the entity segment of the document's
        own ``l10n_latam_document_number``. So the number a fixture hands out is
        not cosmetic here -- it decides the row a document lands in, and
        ``l10n_latam_invoice_document`` declares ``_unique_name`` over
        ``(name, journal_id)`` for every posted move, so a duplicated ``name``
        collides on a constraint the flush raises.
        """
        explicit = self._create_sale(document_number="001-001-000000900")
        self.assertEqual(explicit.l10n_latam_document_number, "001-001-000000900")
        first = self._create_sale()
        second = self._create_sale()
        self.assertEqual(first.l10n_latam_document_number, "001-001-000000001")
        self.assertEqual(second.l10n_latam_document_number, "001-001-000000002")
        # A second establishment gets its own prefix, read off its own journal.
        other = self._second_sale_journal("002")
        theirs = self._create_sale(journal=other)
        self.assertEqual(theirs.l10n_latam_document_number, "002-001-000000003")
        self.assertEqual(
            self.Collector._l10n_ec_triple_from_document_number(theirs)[0], "002"
        )

    # ------------------------------------------------------------------
    # Granularity: one row per codEstab
    # ------------------------------------------------------------------

    def test_01_two_establishments_issuing_on_both_yield_two_rows(self):
        """``CLAVE PRIMARIA (2)`` row 94 keys this block on ``codEstab`` alone."""
        self._create_sale(taxes=self.tax_vat12, products=self.product_gravable)
        second_journal = self._second_sale_journal("002")
        self._create_sale(
            taxes=self.tax_vat12,
            products=self.product_zero,
            journal=second_journal,
        )
        rows = self._rows_by_establishment()
        self.assertEqual(sorted(rows), ["001", "002"])
        for row in rows.values():
            self.assertEqual(sorted(row), ["codEstab", "ventasEstab"])

    def test_02_the_key_is_the_establishment_and_nothing_else(self):
        """Two clients on one establishment are still **one** row.

        ``ventas`` aggregates by client and document type; this block does not
        aggregate on the client at all, so a company invoicing three different
        clients under two document types from one establishment must not produce
        three rows.
        """
        other = self.env["res.partner"].create(
            {
                "name": "Otro Cliente RUC",
                "vat": "1713109678001",
                "l10n_latam_identification_type_id": self.env.ref("l10n_ec.ec_ruc").id,
                "country_id": self.env.ref("base.ec").id,
            }
        )
        self._create_sale(taxes=self.tax_vat12, products=self.product_gravable)
        self._create_sale(
            partner=other, taxes=self.tax_vat12, products=self.product_gravable
        )
        self._create_sale(
            taxes=self.tax_vat12,
            products=self.product_gravable,
            document_type="l10n_ec.ec_dt_02",
        )
        ventas_rows, ventas_errors = self._collect_ventas()
        self.assertFalse(ventas_errors, ventas_errors)
        self.assertEqual(len(ventas_rows), 3, "the ventas block does split three ways")
        estab_rows, estab_errors = self._collect()
        self.assertFalse(estab_errors, estab_errors)
        self.assertEqual(len(estab_rows), 1, "the establishment block does not")

    def test_03_ventas_estab_is_the_sales_total_of_that_establishment(self):
        """The row carries the base total of the documents of its **own**
        establishment, and nothing of anybody else's."""
        first = self._create_sale(taxes=self.tax_vat12, products=self.product_gravable)
        second = self._create_sale(taxes=self.tax_vat12, products=self.product_gravable)
        other = self._create_sale(
            taxes=self.tax_vat12,
            products=self.product_zero,
            journal=self._second_sale_journal("002"),
        )
        rows = self._rows_by_establishment()
        self.assertEqual(
            rows["001"]["ventasEstab"], first.amount_untaxed + second.amount_untaxed
        )
        self.assertEqual(rows["002"]["ventasEstab"], other.amount_untaxed)
        self.assertAlmostEqual(
            rows["001"]["ventasEstab"] + rows["002"]["ventasEstab"],
            first.amount_untaxed + second.amount_untaxed + other.amount_untaxed,
            places=2,
        )

    def test_04_ventas_estab_covers_all_three_buckets_not_only_the_gravable_one(self):
        """``totalVentas`` is the sum of three buckets, so ``ventasEstab`` must be
        built from the same three or the two cannot be compared at all."""
        self._create_sale(taxes=self.tax_vat12, products=self.product_gravable)
        self._create_sale(taxes=self.tax_zero_vat, products=self.product_zero)
        self._create_sale(
            taxes=self.tax_not_charged_vat, products=self.product_not_charged
        )
        self.assertAlmostEqual(self._only_row()["ventasEstab"], 600.0, places=2)

    # ------------------------------------------------------------------
    # totalVentas: gross, computed from the ventas rows
    # ------------------------------------------------------------------

    def test_05_total_ventas_is_the_sum_of_the_three_base_buckets(self):
        """Asserted against a literal, not against another collector output.

        ``ESQUEMA`` row 10 names exactly ``baseNoGraIva``, ``baseImponible`` and
        ``baseImpGrav``. The fixture is one sale per bucket at 100 / 200 / 300,
        so the correct answer is 600.00, and a collector that re-aggregated
        independently, or that added ``montoIva``, would miss it.
        """
        gravable = self._create_sale(
            taxes=self.tax_vat12, products=self.product_gravable
        )
        zero = self._create_sale(taxes=self.tax_zero_vat, products=self.product_zero)
        not_charged = self._create_sale(
            taxes=self.tax_not_charged_vat, products=self.product_not_charged
        )
        ventas_rows, errors = self._collect_ventas()
        self.assertFalse(errors, errors)
        self.assertEqual(gravable.amount_untaxed, 100.0)
        self.assertEqual(zero.amount_untaxed, 200.0)
        self.assertEqual(not_charged.amount_untaxed, 300.0)

        estab_rows, estab_errors = self._collect()
        self.assertFalse(estab_errors, estab_errors)
        header, header_errors = self.Collector.collect_iva_header_with_errors(
            ventas_rows, estab_rows
        )
        self.assertFalse(header_errors, header_errors)
        # The buckets that were summed are the ones the block reports.
        self.assertEqual(
            {
                field: sum(row[field] for row in ventas_rows)
                for field in TOTAL_VENTAS_BUCKETS
            },
            {"baseNoGraIva": 300.0, "baseImponible": 200.0, "baseImpGrav": 100.0},
        )
        self.assertEqual(header["totalVentas"], 600.00)

    def test_06_total_ventas_reads_the_ventas_rows_not_the_documents(self):
        """The ficha marks the box *"casillero no editable"*.

        Re-reading the sales documents instead of summing the rows the
        ``ventas`` collector already produced is exactly how the header and the
        block would drift apart. Asserted structurally: block rows whose
        buckets correspond to no document must be the values that reach the
        header.
        """
        self._create_sale(taxes=self.tax_vat12, products=self.product_gravable)
        fabricated_ventas = [
            {
                "baseNoGraIva": 11.0,
                "baseImponible": 22.0,
                "baseImpGrav": 33.0,
                "numeroComprobantes": 1,
            }
        ]
        fabricated_estab = [{"codEstab": "001", "ventasEstab": 66.0}]
        header, errors = self.Collector.collect_iva_header_with_errors(
            fabricated_ventas, fabricated_estab
        )
        self.assertFalse(errors, errors)
        self.assertEqual(header["totalVentas"], 66.00)

    def test_07_a_period_with_no_sales_reports_a_zero_total(self):
        """An empty period is a legitimate report, not a failure."""
        ventas_rows, _ = self._collect_ventas(period=EMPTY_PERIOD)
        estab_rows, errors = self._collect(period=EMPTY_PERIOD)
        self.assertFalse(errors, errors)
        self.assertEqual(ventas_rows, [])
        self.assertEqual(len(estab_rows), 1, "the establishment is still in the RUC")
        self.assertEqual(estab_rows[0]["ventasEstab"], 0.0)
        header, header_errors = self.Collector.collect_iva_header_with_errors(
            ventas_rows, estab_rows
        )
        self.assertFalse(header_errors, header_errors)
        self.assertEqual(header["totalVentas"], 0.00)

    # ------------------------------------------------------------------
    # numEstabRuc: the count, three digits, never 000
    # ------------------------------------------------------------------

    def test_08_num_estab_ruc_is_the_establishment_count_in_three_digits(self):
        """``numEstabRucType`` carries ``\\d{3``, so seven is ``"007"``."""
        self.assertEqual(self.Collector._l10n_ec_num_estab_ruc(7), "007")
        self.assertEqual(self.Collector._l10n_ec_num_estab_ruc(1), "001")
        self.assertEqual(self.Collector._l10n_ec_num_estab_ruc(100), "100")
        self._create_sale(taxes=self.tax_vat12, products=self.product_gravable)
        for index in range(2, 8):
            self._second_sale_journal(f"00{index}", code=f"SAL{index}")
        rows, errors = self._collect()
        self.assertFalse(errors, errors)
        self.assertEqual(len(rows), 7)
        header, header_errors = self.Collector.collect_iva_header_with_errors(
            self._collect_ventas()[0], rows
        )
        self.assertFalse(header_errors, header_errors)
        self.assertEqual(header["numEstabRuc"], "007")

    def test_09_num_estab_ruc_counts_establishments_not_emission_points(self):
        """§5.9.2: Enterprise derives this from ``l10n_ec_emission``.

        Two journals under one establishment, each with its own emission point,
        are **one** establishment. Counting emission points would file a
        ``numEstabRuc`` of ``002`` for a company the RUC records as one.
        """
        self._create_sale(taxes=self.tax_vat12, products=self.product_gravable)
        second = self._second_sale_journal("001", emission="004", code="SAL4")
        self.assertEqual(second.l10n_ec_entity, self.journal_sale.l10n_ec_entity)
        self.assertNotEqual(second.l10n_ec_emission, self.journal_sale.l10n_ec_emission)
        rows, errors = self._collect()
        self.assertFalse(errors, errors)
        self.assertEqual([row["codEstab"] for row in rows], ["001"])
        header, header_errors = self.Collector.collect_iva_header_with_errors(
            self._collect_ventas()[0], rows
        )
        self.assertFalse(header_errors, header_errors)
        self.assertEqual(header["numEstabRuc"], "001")

    def test_10_zero_establishments_blocks_rather_than_emitting_000(self):
        """The ficha: ``numEstabRuc`` *"debe ser mayor a 000"*.

        ``numEstabRucType`` agrees (``minExclusive 000``), so a file carrying
        ``000`` breaks a business rule *and* the schema. With every journal of
        the company deactivated the composite has nothing to derive from, and
        the honest answer is a refusal.
        """
        journals = self.env["account.journal"].search(
            [("company_id", "=", self.company.id)]
        )
        self.assertTrue(journals)
        journals.write({"active": False})
        self.assertFalse([journal for journal in journals if journal.active])

        rows, errors = self._collect(period=EMPTY_PERIOD)
        self.assertEqual(rows, [])
        self.assertEqual(errors, [], "an absent establishment is not itself an error")
        header, header_errors = self.Collector.collect_iva_header_with_errors([], rows)
        self.assertEqual(header, {})
        self.assertEqual([error["field"] for error in header_errors], ["numEstabRuc"])
        self.assertNotIn("numEstabRuc", header)

    # ------------------------------------------------------------------
    # The 000 rule, where the schema finally agrees with the ficha
    # ------------------------------------------------------------------

    def test_11_a_journal_entity_of_000_is_rejected_and_named(self):
        """``account.journal`` accepts ``000`` today.

        ``l10n_ec_base/models/account_journal.py:18`` checks only
        ``len(value) < 3`` and ``not value.isnumeric()``, and ``"000"``
        satisfies both, so nothing upstream prevents this from being written.
        """
        journal = self._second_sale_journal("000", code="SAL0")
        self.assertEqual(journal.l10n_ec_entity, "000")
        self.assertGreaterEqual(len(journal.l10n_ec_entity), 3)
        self.assertTrue(journal.l10n_ec_entity.isnumeric())

        rows, errors = self._collect(period=EMPTY_PERIOD)
        self.assertNotIn("000", [row["codEstab"] for row in rows])
        rejected = [error for error in errors if error["field"] == "codEstab"]
        self.assertEqual(len(rejected), 1, errors)
        self.assertEqual(rejected[0]["journal"], journal)
        self.assertIn(journal.display_name, str(rejected[0]["message"]))
        self.assertIn("000", str(rejected[0]["message"]))

    def test_12_a_zero_establishment_is_refused_on_both_derivations(self):
        """The journal pair and the recorded document number both feed the set.

        A journal set to ``000`` also stamps ``000-001-...`` onto every
        document it issues, so both derivations see it and both refuse it --
        once against the journal and once against the document that carries it.
        """
        journal = self._second_sale_journal("000", code="SAL0")
        invoice = self._create_sale(
            taxes=self.tax_vat12, products=self.product_gravable, journal=journal
        )
        self.assertEqual(
            self.Collector._l10n_ec_triple_from_document_number(invoice)[0], "000"
        )

        rows, errors = self._collect()
        self.assertNotIn("000", [row["codEstab"] for row in rows])
        self.assertEqual(len(rows), 1, "the valid establishment still files")
        self.assertEqual(rows[0]["codEstab"], "001")
        rejected = [error for error in errors if error["field"] == "codEstab"]
        self.assertEqual(len(rejected), 2, errors)
        self.assertEqual(rejected[0]["journal"], journal)
        self.assertEqual(rejected[1]["move"], invoice)
        self.assertIn("001", str(rejected[1]["message"]))

    def test_13_a_journal_with_no_entity_is_skipped_not_emitted(self):
        """``sale_withhold_ec`` is seeded with an **empty** entity and emission.

        Not hypothetical: ``l10n_ec_withhold/data/template/account.journal-ec.csv``
        ships that row empty and it is an active journal of every EC company.
        Emitting it would put a blank ``codEstab`` in the file, which
        ``ventasEstabType``'s ``\\d{3}`` would reject.
        """
        withhold = self.journal_sale_withhold
        self.assertFalse(withhold.l10n_ec_entity, "the seeded row is empty")
        self.assertTrue(withhold.active)
        self.assertEqual(withhold.company_id, self.company)
        self._create_sale(taxes=self.tax_vat12, products=self.product_gravable)
        rows = self._rows_by_establishment()
        self.assertEqual(sorted(rows), ["001"])
        for code in rows:
            self.assertEqual(len(code), 3)
            self.assertTrue(code.isdigit())

    # ------------------------------------------------------------------
    # The establishment set: the RUC set, not the selling set
    # ------------------------------------------------------------------

    def test_14_an_establishment_without_sales_yields_a_zero_row(self):
        """The ficha text that decides it.

        *"Se debe registrar el valor total de las ventas por establecimiento.
        Debe generarse igual número de registros que el valor informado en el
        campo número de establecimientos del sujeto pasivo, inscritos en el
        RUC."*

        The row count is tied to ``numEstabRuc``, and ``numEstabRuc`` counts
        establishments *inscribed in the RUC* -- an active establishment of the
        taxpayer, not one that happened to sell. So an establishment with no
        sales is still a row carrying ``0.00``.
        """
        self._second_sale_journal("002")
        self._create_sale(taxes=self.tax_vat12, products=self.product_gravable)
        rows = self._rows_by_establishment()
        self.assertEqual(sorted(rows), ["001", "002"])
        self.assertEqual(rows["002"]["ventasEstab"], 0.0)
        self.assertGreater(rows["001"]["ventasEstab"], 0.0)
        header, errors = self._header()
        self.assertFalse(errors, errors)
        self.assertEqual(header["numEstabRuc"], "002")

    def test_15_the_set_unions_the_journals_with_the_issued_document_numbers(self):
        """§5.2: distinct ``l10n_ec_entity`` over active journals, **unioned**
        with the entity segment of ``l10n_latam_document_number``.

        The union is not redundant. Changing a journal's entity after a
        document was issued leaves the establishment that document was really
        filed under with no journal declaring it any more, and reading only the
        journals would drop a real establishment from the ``numEstabRuc`` count.
        """
        invoice = self._create_sale(
            taxes=self.tax_vat12, products=self.product_gravable
        )
        self.assertIn("001-", invoice.l10n_latam_document_number)
        self.assertEqual(
            self.Collector._l10n_ec_triple_from_document_number(invoice)[0], "001"
        )

        self.journal_sale.l10n_ec_entity = "007"
        rows = self._rows_by_establishment()
        self.assertEqual(sorted(rows), ["001", "007"])
        # The sale belongs to the establishment its own document names.
        self.assertEqual(rows["001"]["ventasEstab"], invoice.amount_untaxed)
        self.assertEqual(rows["007"]["ventasEstab"], 0.0)
        header, errors = self._header()
        self.assertFalse(errors, errors)
        self.assertEqual(header["numEstabRuc"], "002")

    def test_16_a_draft_or_out_of_window_sale_adds_no_establishment(self):
        """The document side of the union reads the period's **posted** sales."""
        self._create_sale(taxes=self.tax_vat12, products=self.product_gravable)
        draft = self._create_sale(taxes=self.tax_vat12, products=self.product_gravable)
        draft.button_draft()
        self._create_sale(
            taxes=self.tax_vat12,
            products=self.product_gravable,
            posting_date=date(2016, 5, 10),
        )
        self.assertEqual(sorted(self._rows_by_establishment()), ["001"])

    def test_17_a_vendor_bill_is_not_our_establishment(self):
        """``compras`` files the **supplier's** triple; this block is ours.

        The two derivations look alike -- both read
        ``l10n_latam_document_number`` -- and reading each other's subject by
        mistake is the error §5.2 exists to prevent.
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
            l10n_latam_document_number="004-004-000000900",
        )
        bill.write({"date": PERIOD[0], "invoice_date": PERIOD[0]})
        bill.l10n_ec_tax_support = "01"
        bill.l10n_ec_authorization_number = "123456789012"
        bill.action_post()

        self._create_sale(taxes=self.tax_vat12, products=self.product_gravable)
        rows = self._rows_by_establishment()
        self.assertEqual(sorted(rows), ["001"])
        self.assertNotIn("004", rows)

    # ------------------------------------------------------------------
    # The row keys on the entity, never the emission point
    # ------------------------------------------------------------------

    def test_18_the_row_keys_on_the_entity_not_the_emission_point(self):
        """The distinction §5.2 exists to keep, and Enterprise gets wrong.

        ``codEstab`` is *"el código del establecimiento (conforme inscripción en
        el RUC)"*. ``l10n_ec_emission`` is the *punto de emisión*: a different
        axis entirely, several per establishment.
        """
        self.journal_sale.write({"l10n_ec_entity": "001", "l10n_ec_emission": "009"})
        self._create_sale(taxes=self.tax_vat12, products=self.product_gravable)
        invoice = self.env["account.move"].search(
            [("move_type", "=", "out_invoice"), ("state", "=", "posted")], limit=1
        )
        self.assertEqual(invoice.journal_id.l10n_ec_entity, "001")
        self.assertEqual(invoice.journal_id.l10n_ec_emission, "009")
        self.assertEqual(invoice.l10n_latam_document_number.split("-")[0], "001")

        rows = self._rows_by_establishment()
        self.assertEqual(list(rows), ["001"])
        self.assertNotIn("009", rows)
        header, errors = self._header()
        self.assertFalse(errors, errors)
        self.assertEqual(header["numEstabRuc"], "001")

    def test_19_two_establishments_sharing_one_emission_point_stay_two_rows(self):
        """The mirror image, so neither half of the confusion survives."""
        self._second_sale_journal("002", emission="001", code="SAL2")
        self._create_sale(taxes=self.tax_vat12, products=self.product_gravable)
        rows = self._rows_by_establishment()
        self.assertEqual(sorted(rows), ["001", "002"])
        self.assertEqual({row["ventasEstab"] for row in rows.values()}, {0.0, 100.0})

    # ------------------------------------------------------------------
    # ivaComp: omitted, deliberately
    # ------------------------------------------------------------------

    def test_20_iva_comp_is_omitted_and_the_catalog_is_loaded(self):
        """``Tabla 21`` **is** loaded; nothing in Odoo records a compensation.

        Asserting the catalog first is the point: the omission must be a
        decision about a missing *source*, not an accident of a table that
        failed to import. Read through ``_applicable_on`` rather than against
        the table, because ``Tabla 21`` is effective-dated and neither code is
        in force on the day ``PERIOD`` starts.
        """
        self.assertEqual(self._catalog_codes("21", PERIOD[0]), [])
        self.assertEqual(self._catalog_codes("21", TABLA_21_DATE), ["01", "02"])
        table = self.CatalogTable.search([("code", "=", "21")])
        self.assertTrue(table.in_scope)
        self.assertEqual(table.entry_count, 2)

        self._create_sale(taxes=self.tax_vat12, products=self.product_gravable)
        rows, errors = self._collect()
        self.assertFalse(errors, errors)
        self.assertEqual(len(rows), 1)
        self.assertNotIn("ivaComp", rows[0])

        # The reason, kept honest as a guard: if a compensation ever becomes a
        # record, this test must fail and force the decision to be taken again
        # rather than a real ``ivaComp`` being silently dropped. Matched on
        # "compens" and not "comp", which would match ``company_*`` and every
        # ``compute_*`` field in the model.
        carriers = [
            name
            for model in ("account.move", "account.move.line", "account.journal")
            for name in self.env[model]._fields
            if "compens" in name.lower()
        ]
        self.assertEqual(
            carriers, [], "a recordable IVA compensation would change this decision"
        )

    # ------------------------------------------------------------------
    # Blocking conditions
    # ------------------------------------------------------------------

    def test_21_a_document_type_outside_tabla_4_blocks_the_establishment_row(self):
        """The ``000``-free guard: a code the SRI never published.

        Every document type the EC localization ships *is* a ``Tabla 4`` code
        and a draft cannot be given one that is not, so the code is changed
        after posting -- what a retired catalog row or a mis-keyed record looks
        like by filing time. Both blocks read the same document and both refuse
        it.
        """
        self.assertNotIn("99", self._catalog_codes("04", PERIOD[0]))
        invoice = self._create_sale(
            taxes=self.tax_vat12, products=self.product_gravable
        )
        invoice.l10n_latam_document_type_id.code = "99"
        self.assertEqual(invoice.l10n_latam_document_type_id.code, "99")

        rows, errors = self._collect()
        self.assertEqual(rows, [])
        self.assertIn("tipoComprobante", [error["field"] for error in errors])
        self.assertIn("99", str(errors[0]["message"]))
        self.assertEqual(self._collect_ventas()[0], [])

    def test_22_a_document_type_outside_the_reported_period_blocks_the_row(self):
        """The regression guard for the chained-``search`` temporal defect.

        ``BaseModel.search`` is ``@api.model``, so a collector that filtered its
        temporal read by chaining a ``search`` onto a recordset would discard
        the window and hand back every era at once. ``Tabla 4`` states no
        ``Fecha de vigencia`` of its own -- the sheet spells that column
        ``vacío`` in all forty rows -- so the window is set here to the one the
        SRI's own history would give the row: in force from 2020, absent before.
        """
        entry = self._catalog_entry("04", "18")
        self.assertTrue(entry, "Tabla 4 must publish code 18 at all")
        entry.date_start = date(2020, 1, 1)
        # The catalog's own facts, asserted before anything derived from them.
        self.assertIn("18", self._catalog_codes("04", MODERN_PERIOD[0]))
        self.assertNotIn("18", self._catalog_codes("04", PERIOD[0]))

        self._create_sale(
            taxes=self.tax_vat12,
            products=self.product_gravable,
            document_type="l10n_ec.ec_dt_18",
        )
        rows, errors = self._collect()
        self.assertEqual(rows, [])
        self.assertEqual([error["field"] for error in errors], ["tipoComprobante"])
        self.assertIn("18", str(errors[0]["message"]))

    def test_23_the_same_document_type_is_accepted_for_a_period_that_covers_it(self):
        """The counterpart: the very row :meth:`test_22` refuses for March is
        filed for a period the catalog does cover."""
        self._catalog_entry("04", "18").date_start = date(2020, 1, 1)
        self._create_sale(
            taxes=self.tax_vat12,
            products=self.product_gravable,
            document_type="l10n_ec.ec_dt_18",
            posting_date=MODERN_PERIOD[0],
        )
        row = self._only_row(period=MODERN_PERIOD)
        self.assertEqual(row["codEstab"], "001")
        self.assertEqual(row["ventasEstab"], 100.0)

    def test_24_fecha_registro_outside_the_reported_month_blocks(self):
        """``fechaRegistro`` must **equal** the period, not merely fall in it."""
        self._create_sale(
            taxes=self.tax_vat12,
            products=self.product_gravable,
            posting_date=date(2016, 2, 15),
        )
        rows, errors = self._collect(period=(date(2016, 1, 1), date(2016, 3, 31)))
        self.assertEqual(rows, [])
        self.assertEqual([error["field"] for error in errors], ["fechaRegistro"])

    # ------------------------------------------------------------------
    # The two invariants, asserted arithmetically
    # ------------------------------------------------------------------

    def test_25_without_a_credit_note_the_two_agree_exactly(self):
        """``totalVentas == sum(ventasEstab)`` when nothing reduces the sale.

        This is the equality case, and it doubles as the **bucket-definition
        drift guard**: ``ventasEstab`` is built per document and
        ``totalVentas`` out of the aggregated rows, so if the two disagreed
        about which buckets count they would part company right here.
        """
        self._create_sale(taxes=self.tax_vat12, products=self.product_gravable)
        self._create_sale(taxes=self.tax_zero_vat, products=self.product_zero)
        self._create_sale(
            taxes=self.tax_not_charged_vat, products=self.product_not_charged
        )
        estab_rows, errors = self._collect()
        self.assertFalse(errors, errors)
        header, header_errors = self._header()
        self.assertFalse(header_errors, header_errors)
        self.assertEqual(header["totalVentas"], 600.00)
        self.assertAlmostEqual(
            sum(row["ventasEstab"] for row in estab_rows), 600.00, places=2
        )

    def test_26_a_credit_note_reduces_ventas_estab_and_never_goes_below(self):
        """The ``ESQUEMA`` row 103 rule, arithmetically.

        A 300.00 sale and a 100.00 credit note net to 200.00, so the row reads
        200.00 while ``totalVentas`` -- the sum of the three **absolute**
        buckets per row 10 -- reads 400.00. The gap is exactly twice the credit
        note, which is the margin the ficha's *"no puede ser mayor"* allows.
        """
        sale = self._create_sale(
            taxes=self.tax_vat12, products=self.product_not_charged
        )
        note = self._create_credit_note(
            taxes=self.tax_vat12, products=self.product_gravable
        )
        self.assertEqual(sale.amount_untaxed, 300.0)
        self.assertEqual(note.amount_untaxed, -100.0)

        ventas_rows, ventas_errors = self._collect_ventas()
        self.assertFalse(ventas_errors, ventas_errors)
        self.assertEqual(
            sorted(row["tipoComprobante"] for row in ventas_rows), ["01", "04"]
        )
        # The block reports magnitudes under each document type, both positive.
        self.assertEqual(
            sorted(row["baseImpGrav"] for row in ventas_rows), [100.0, 300.0]
        )

        estab_rows, estab_errors = self._collect()
        self.assertFalse(estab_errors, estab_errors)
        header, header_errors = self.Collector.collect_iva_header_with_errors(
            ventas_rows, estab_rows
        )
        self.assertFalse(header_errors, header_errors)
        self.assertEqual(header["totalVentas"], 400.00)
        self.assertEqual(estab_rows[0]["ventasEstab"], 200.0)
        self.assertAlmostEqual(
            sum(row["ventasEstab"] for row in estab_rows), 200.00, places=2
        )
        # The ceiling the ficha states, and its exact margin.
        self.assertGreaterEqual(
            header["totalVentas"], sum(row["ventasEstab"] for row in estab_rows)
        )
        self.assertAlmostEqual(
            header["totalVentas"] - sum(row["ventasEstab"] for row in estab_rows),
            2 * abs(note.amount_untaxed),
            places=2,
        )

    def test_27_a_credit_note_drives_the_row_negative_and_is_not_clamped(self):
        """``totalVentasType`` admits a minus and ``ventasEstab`` is typed as one.

        A company crediting more than it invoiced from one establishment has a
        genuinely negative net figure. Clamping it to ``0.00`` would state a
        number the company never had, and the schema can carry the real one.
        """
        self._create_credit_note(
            taxes=self.tax_vat12, products=self.product_not_charged
        )
        self._create_credit_note(taxes=self.tax_vat12, products=self.product_gravable)
        estab_rows, estab_errors = self._collect()
        self.assertFalse(estab_errors, estab_errors)
        self.assertEqual(estab_rows[0]["ventasEstab"], -400.0)

        ventas_rows, ventas_errors = self._collect_ventas()
        self.assertFalse(ventas_errors, ventas_errors)
        header, header_errors = self.Collector.collect_iva_header_with_errors(
            ventas_rows, estab_rows
        )
        self.assertFalse(header_errors, header_errors)
        # Both credit notes are reported as magnitudes, so the header stays
        # positive and the two blocks differ by twice the whole period.
        self.assertEqual(header["totalVentas"], 400.00)

    # ------------------------------------------------------------------
    # Row shape
    # ------------------------------------------------------------------

    def test_28_the_row_keys_are_exactly_the_ats_element_names(self):
        """ATS-10 is a straight mapping, so the keys must be the XSD names."""
        self._create_sale(taxes=self.tax_vat12, products=self.product_gravable)
        row = self._only_row()
        self.assertEqual(set(row), {"codEstab", "ventasEstab"})
        for absent in (
            "establecimiento",
            "puntoEmision",
            "secuencial",
            "numeroComprobantes",
            "baseNoGraIva",
            "baseImponible",
            "baseImpGrav",
            "montoIva",
            "ivaComp",
            "compensaciones",
            "tipoComprobante",
        ):
            self.assertNotIn(absent, row)

    def test_29_the_catalog_keyword_lookups_still_fold_accents(self):
        """Every catalog keyword lookup goes through the accent folder.

        The SRI spells its descriptions with accents -- *Facturación Física* --
        so a comparison against a keyword written without them would stop
        matching the moment the source was reissued. Pinned here rather than in
        one block's suite, because this block shares those helpers.
        """
        collector = self.Collector
        # ``Tabla 4`` stores its codes **unpadded** -- ``4``, not ``04`` -- which
        # is exactly the disagreement ``_l10n_ec_same_code`` exists to forgive.
        entry = self._catalog_entry("04", "4")
        self.assertTrue(entry, "Tabla 4 must publish the credit note")
        self.assertEqual(entry.code, "4")
        self.assertTrue(collector._l10n_ec_description_contains(entry, "NOTA DE CR"))
        self.assertFalse(collector._l10n_ec_description_contains(entry, "NOTA DE DE"))
        self.assertEqual(
            collector._l10n_ec_strip_accents("Compañía Ñandú áéíóú"),
            "Compania Nandu aeiou",
        )
        for table_code, keyword in (
            ("04", "NOTA DE CR"),
            ("14", "SOCIEDAD"),
            ("20", "ELECTRONICA"),
        ):
            matching = [
                candidate
                for candidate in self.CatalogEntry._applicable_on(PERIOD[0])
                if candidate.table_id.code == table_code
                and collector._l10n_ec_description_contains(candidate, keyword)
            ]
            self.assertTrue(matching, (table_code, keyword))
