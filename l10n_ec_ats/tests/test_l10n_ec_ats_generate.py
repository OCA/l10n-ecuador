"""The generation wizard: the one seam that closes the ATS pipeline.

Four layers ship before this one -- ``collector`` reads records into block
payloads, ``builder`` renders those payloads into XML, ``validators`` applies
the business rules the schema cannot express and ``schema`` checks the result
against ``ats.xsd``. None of them is reachable by a user, so none of them can be
proven to work on real data. The wizard is the layer that composes them, and it
is the layer where the two rules this project exists to enforce become visible:

* **Nothing is assumed.** Every catalog read resolves through
  ``_applicable_on(period)`` and must return **exactly one** entry. Zero is a
  coverage hole, more than one is an overlap, and both stop generation naming
  the table, the code and the window. There is no fallback and no default.
* **Nothing is silently dropped.** A document that cannot be completed without
  inventing a value is reported against the document and the field, and
  generation stops. Odoo Enterprise fabricates ``'9999999999'`` for a missing
  vendor authorization; ATS refuses the file instead.

Every problem found is **aggregated into one** ``UserError``. One error per
lookup would make a bad period unreadable: a company fixing March would have to
run generation twenty times to see twenty problems.

The four negative paths below are the ones acceptance criterion 7 and §5.6
Level 3 name -- a catalog gap, a catalog overlap, an unresolved ``Tabla 3.10``
rate and missing source data -- and each raises a ``UserError`` naming the
table, the code and the window rather than a bare ``False``.

``test_historical_period_files_a_different_document`` is the one that proves the
temporal resolution is real. Two periods, one fixture, two files, and the only
thing that differs between them is a ``porcentajeAir`` read out of ``Tabla
3.10`` for that period: concept ``304`` is 8% through the 2016 era and 10% from
2024. Delete the date from the lookup and the two files become identical while
every other assertion in this suite still passes.
"""

import io
import zipfile
from datetime import date, timedelta

from lxml import etree

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.l10n_ec_account_edi.tests.test_edi_common import TestL10nECEdiCommon

from ..validators import AtsPeriod, blocking, validate_ats, warnings_of

#: A period every loaded catalog covers and where the VAT regime is the current
#: one. The archive is named ``AT082026.zip``: month then year, both two and
#: four digits, no separator and no special character.
CURRENT = (2026, 8)
#: ``Tabla 12`` was in its 14% regime on this day, so a 12% tax reconciles with
#: an *alerta* rather than exactly -- which is how the warning path is reached
#: without weakening anything.
HISTORICAL = (2016, 6)
#: ``Tabla 13`` publishes the debit- and credit-card forms from 2016-05-01 and
#: 2016-06-01, so form ``20`` has **no** window covering this month. Used to
#: reach the catalog-gap path with shipped data and no mutation at all.
BEFORE_CARD_FORMS = (2016, 3)
#: ``Tabla 11`` codes ``9`` and ``10`` -- the 10% and 20% IVA withholdings --
#: start on 2015-06-01, so this month predates them. The second catalog-gap path.
BEFORE_TABLA11_SHARES = (2015, 3)
#: The only era ``Tabla 3.10`` gives concept ``302`` is 2024-04-01 to
#: 2024-06-30, and in it the source cell states no single percentage. Used to
#: reach the unresolved-rate path.
UNRESOLVED_AIR = (2024, 5)
#: A year the ficha's ``ESQUEMA`` rules out: *"El año debe corresponder a
#: periodos del 2000 en adelante"*.
BEFORE_THE_CALENDAR = 1999

#: The archive name the ficha spells: ``AT{mmaaaa}``, no separator.
CURRENT_ARCHIVE = "AT082026.zip"
HISTORICAL_ARCHIVE = "AT062016.zip"

#: ``RUC_SOCIEDAD`` module 11 verified, and the same body with its verifier
#: altered. Taken from ``test_l10n_ec_ats_validators``: one module, one truth.
ONE_DAY = timedelta(days=1)
RUC_VALID = "0992301287001"
RUC_BAD_CHECK_DIGIT = "0992301287002"


@tagged("post_install_l10n", "post_install", "-at_install")
class TestL10nEcAtsGenerate(TestL10nECEdiCommon):
    """One company, one period, one ``AT{mmaaaa}.zip`` holding one valid XML."""

    @classmethod
    @AccountTestInvoicingCommon.setup_country("ec")
    @AccountTestInvoicingCommon.setup_chart_template("ec")
    def setUpClass(cls):
        super().setUpClass()
        cls()._setup_edi_company_ec()
        cls.chart_template = cls.env["account.chart.template"].with_company(cls.company)
        cls.journal_sale = cls.company_data["default_journal_sale"]
        cls.journal_purchase = cls.company_data["default_journal_purchase"]
        # The EC chart ships two purchase journals and ``TestL10nECCommon``
        # points at the liquidation one; the ordinary vendor-bill journal is the
        # one this pipeline reports.
        cls.journal_purchase.write(
            {
                "l10n_ec_emission_address_id": cls.partner_contact.id,
                "l10n_ec_sri_payment_id": cls.env.ref("l10n_ec.P1").id,
                "l10n_latam_use_documents": True,
                "l10n_ec_entity": "001",
                "l10n_ec_emission": "001",
            }
        )
        cls.journal_purchase_withhold = cls.chart_template.ref("purchase_withhold_ec")
        cls.journal_sale_withhold = cls.chart_template.ref("sale_withhold_ec")
        cls.tax_vat12 = cls.chart_template.ref("tax_vat_510_sup_01")
        cls.tax_air_304 = cls.chart_template.ref("tax_withhold_profit_304_10")
        cls.tax_sale_withhold_vat_100 = cls.chart_template.ref(
            "tax_sale_withhold_vat_100"
        )

    # ------------------------------------------------------------------
    # Fixtures
    # ------------------------------------------------------------------

    def _wizard(self, period=CURRENT, company=None):
        """Create the wizard for ``period``, a ``(year, month)`` pair."""
        year, month = period
        return (
            self.env["l10n.ec.ats.generate"]
            .with_context(active_model="l10n.ec.ats.generate")
            .create(
                {
                    "company_id": (company or self.company).id,
                    "anio": year,
                    "mes": month,
                }
            )
        )

    def _create_bill(
        self,
        *,
        document_number="001-001-000000123",
        tax_support="01",
        authorization="123456789012",
        posting_date=None,
        taxes=None,
    ):
        """Post one vendor bill carrying everything a ``compras`` row needs.

        ``l10n_ec_authorization_number`` is written **after** posting: it is a
        stored compute off ``edi_document_ids`` and posting creates that record,
        so a value written beforehand is recomputed away. It is also the
        production shape -- nothing parses a vendor's XML yet, so on a vendor
        bill the number is typed in rather than derived.
        """
        invoice = self._l10n_ec_create_in_invoice(
            self.partner_ruc,
            taxes=taxes or self.tax_vat12,
            journal=self.journal_purchase,
            latam_document_type=self.env.ref("l10n_ec.ec_dt_01"),
            auto_post=False,
            l10n_latam_document_number=document_number,
        )
        invoice.write(
            {
                "date": posting_date or date(*CURRENT, 3),
                "invoice_date": posting_date or date(*CURRENT, 3),
            }
        )
        invoice.l10n_ec_tax_support = tax_support
        invoice.action_post()
        if authorization:
            invoice.l10n_ec_authorization_number = authorization
        return invoice

    def _create_sale(self, *, sri_payment="l10n_ec.P1", posting_date=None):
        """Post one customer invoice for the period.

        The SRI EDI format validates a sale we issue at posting time, which is
        why ``setUpClass`` configures the company through ``_setup_edi_company_ec``.
        """
        form = self._l10n_ec_create_form_move(
            move_type="out_invoice",
            internal_type="invoice",
            partner=self.partner_ruc,
            taxes=self.tax_vat12,
            journal=self.journal_sale,
            latam_document_type=self.env.ref("l10n_ec.ec_dt_01"),
            use_payment_term=False,
        )
        invoice = form.save()
        posting_date = posting_date or date(*CURRENT, 5)
        invoice.write(
            {
                "date": posting_date,
                "invoice_date": posting_date,
                "l10n_ec_sri_payment_id": self.env.ref(sri_payment).id,
            }
        )
        invoice.action_post()
        return invoice

    def _setup_withholding_company(self):
        """What the withholding journals validate against at posting time.

        A withholding posts through the SRI EDI format, so it needs the company's
        RUC, a loaded certificate, the invoice XML version and a street on the
        journal's emission address. Set up directly rather than through
        ``_setup_edi_company_ec``, which also rewrites the sales and vendor-bill
        journals and would move the documents already created.
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
        self.journal_purchase_withhold.l10n_ec_emission_address_id = (
            self.partner_contact.id
        )
        self.journal_sale_withhold.l10n_ec_emission_address_id = self.partner_contact.id

    def _withhold(self, document, tax, journal, withholding_type):
        """Post a withholding against ``document`` and link the two.

        Mirrors what the ``l10n_ec_withhold`` wizards produce -- the basis, the
        counterpart, and ``l10n_ec_invoice_withhold_id`` on the basis line, which
        is the only link the collector follows. The basis is what the wizard would
        compute: the document's own tax for a VAT withholding, its untaxed amount
        for an income one.

        ``ref`` is the withholding's own number and is made unique per call,
        because ``l10n_ec_withhold`` constrains a sale withholding to one number
        per client -- a real restriction, not a test artefact.
        """
        self._setup_withholding_company()
        self._withhold_seq = getattr(self, "_withhold_seq", 0) + 1
        base = (
            abs(document.amount_tax_signed)
            if tax.tax_group_id.l10n_ec_type == "withhold_vat_purchase"
            else abs(document.amount_untaxed_signed)
        )
        lines = []
        for tax_data in tax.compute_all(base).get("taxes", []):
            amount = abs(tax_data.get("base"))
            lines.append(
                (
                    0,
                    0,
                    {
                        "partner_id": document.partner_id.id,
                        "quantity": 1.0,
                        "price_unit": amount,
                        "account_id": tax_data.get("account_id"),
                        "name": "AIR test basis",
                        "debit": amount,
                        "credit": 0.0,
                        "tax_ids": [(6, 0, tax.ids)],
                        "display_type": "product",
                        "l10n_ec_invoice_withhold_id": document.id,
                        "l10n_ec_tax_support": "01",
                    },
                )
            )
            lines.append(
                (
                    0,
                    0,
                    {
                        "partner_id": document.partner_id.id,
                        "quantity": 1.0,
                        "price_unit": amount,
                        "account_id": tax_data.get("account_id"),
                        "name": "Counterpart AIR",
                        "debit": 0.0,
                        "credit": amount,
                        "tax_ids": [],
                    },
                )
            )
        withholding = self.env["account.move"].create(
            {
                "journal_id": journal.id,
                "date": document.date,
                "move_type": "entry",
                "partner_id": document.partner_id.id,
                "ref": f"ATS-TEST-{self._withhold_seq:04d}",
                "l10n_latam_document_type_id": self.env.ref("l10n_ec.ec_dt_07").id,
                "l10n_ec_withholding_type": withholding_type,
                "line_ids": lines,
            }
        )
        withholding._post()
        document.l10n_ec_withhold_ids = [(4, withholding.id)]
        return withholding

    def _create_purchase_withholding(self, bill, tax):
        """A purchase-side income withholding, which is what ``air`` reads."""
        return self._withhold(bill, tax, self.journal_purchase_withhold, "purchase")

    def _create_sale_withholding(self, invoice, tax):
        """A sale-side IVA withholding, which is what ``valorRetIva`` reads."""
        return self._withhold(invoice, tax, self.journal_sale_withhold, "sale")

    def _archive(self, attachment):
        """``{member name: bytes}`` of an ATS archive, asserting one member."""
        with zipfile.ZipFile(io.BytesIO(attachment.raw)) as archive:
            return archive.namelist(), {
                name: archive.read(name) for name in archive.namelist()
            }

    def _xml_of(self, attachment):
        names, members = self._archive(attachment)
        self.assertEqual(len(names), 1, names)
        return members[names[0]].decode("utf-8")

    # ------------------------------------------------------------------
    # Acceptance criterion 2: the file itself
    # ------------------------------------------------------------------

    def test_01_the_archive_is_named_for_the_month_and_holds_one_valid_xml(self):
        """Criterion 2, verbatim: ``AT{mmaaaa}.zip`` holding one XML that passes
        ``ats.xsd``. Asserted in four parts because each can fail alone.

        The period carries **purchases only**, and that is a fixture choice rather
        than a rule consequence: the sale side is exercised in ``test_01b`` (with
        a client-side IVA withholding) and in ``test_02b`` (without one), because
        ATS-11's ``valorRetIva`` rule behaves differently in those two cases and a
        single sale fixture could only cover one of them.
        """
        self._create_bill()
        attachment, violations = self._wizard()._l10n_ec_run()
        # 1. The name. ``mm`` then ``aaaa``, no separator, no special character.
        self.assertEqual(attachment.name, CURRENT_ARCHIVE)
        self.assertTrue(attachment.name.startswith("AT"))
        self.assertTrue(attachment.name.endswith(".zip"))
        # 2. Exactly one member, and it is the XML.
        names, members = self._archive(attachment)
        self.assertEqual(len(names), 1, names)
        member = names[0]
        self.assertTrue(member.endswith(".xml"), member)
        # 3. The document root and its two single-value enumerations.
        xml_string = members[member].decode("utf-8")
        root = etree.fromstring(xml_string.encode("utf-8"))
        self.assertEqual(root.tag, "iva")
        self.assertEqual(root.findtext("codigoOperativo"), "IVA")
        self.assertEqual(root.findtext("TipoIDInformante"), "R")
        self.assertEqual(root.findtext("Anio"), str(CURRENT[0]))
        self.assertEqual(root.findtext("Mes"), f"{CURRENT[1]:02d}")
        # The header the collectors derived, and the purchases the wizard reported.
        self.assertEqual(root.findtext("numEstabRuc"), "001")
        self.assertEqual(len(root.findall("compras/detalleCompras")), 1)
        # 4. The two validation layers agreed: nothing blocked, and the schema
        #    accepted the document the builder produced.
        self.assertEqual([str(v) for v in violations if v.blocking], [])
        from ..schema import validate_ats_xml

        self.assertTrue(validate_ats_xml(xml_string).is_valid)
        # And the file is attached to the wizard, not floating.
        self.assertTrue(attachment.res_model)
        self.assertEqual(attachment.mimetype, "application/zip")

    def test_01b_the_ventas_block_reaches_the_file_when_the_client_withheld_iva(self):
        """The sale side, end to end, with a real client-side IVA withholding.

        A 100% withholding, so the whole base comes back as ``valorRetIva`` -- a
        value that **is** one ``Tabla 11`` share of the base and therefore
        validates cleanly rather than as an alerta. ``test_02b`` is the twin for
        the ``0.00`` case; between them the two readings of the ``valorRetIva``
        cell are both exercised against the loaded catalog.
        """
        self._create_bill()
        invoice = self._create_sale()
        self._create_sale_withholding(invoice, self.tax_sale_withhold_vat_100)
        attachment, violations = self._wizard()._l10n_ec_run()
        self.assertEqual([str(v) for v in violations if v.blocking], [], violations)
        root = etree.fromstring(self._xml_of(attachment).encode("utf-8"))
        rows = root.findall("ventas/detalleVentas")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].findtext("numeroComprobantes"), "1")
        # A 100% IVA withholding, so the whole base comes back as valorRetIva.
        self.assertEqual(rows[0].findtext("valorRetIva"), "1000.00")
        # ``totalVentas`` is the sum of the three buckets over the ventas rows,
        # and ``ventasEstab`` is the establishment's net -- both defined that way.
        self.assertEqual(root.findtext("totalVentas"), "1000.00")
        self.assertEqual(
            root.findtext("ventasEstablecimiento/ventaEst/ventasEstab"), "1000.00"
        )
        from ..schema import validate_ats_xml

        self.assertTrue(validate_ats_xml(self._xml_of(attachment)).is_valid)

    def test_02_generate_returns_a_download_action_for_the_attachment(self):
        self._create_bill()
        action = self._wizard().generate()
        self.assertEqual(action["type"], "ir.actions.act_url")
        self.assertIn("/web/content/", action["url"])
        attachment_id = int(action["url"].split("/web/content/")[1].split("?")[0])
        self.assertEqual(
            self.env["ir.attachment"].browse(attachment_id).name, CURRENT_ARCHIVE
        )

    def test_02b_a_sale_with_no_client_side_iva_withholding_is_still_filed(self):
        """A ``ventas`` row whose client withheld nothing is **not** a grave error.

        ``ESQUEMA`` row 24 reads: *"Debe ser igual a la baseImpGrav aplicando el
        porcentajeIva (tabla 11). **El valor puede ser mayor o igual**, si no existe
        valor colocar 0.00"*. The last clause sanctions ``0.00`` explicitly -- it is
        what the cell says to file when there is no withholding -- so the first
        sentence's *"debe ser igual"* cannot be read as a floor on the lowest
        ``Tabla 11`` share. Read as a floor, ``0.00`` against a non-zero
        ``baseImpGrav`` is a ``SEVERITY_ERROR``, and **a company whose clients do
        not withhold IVA cannot file a sales period at all**. Most companies are
        that company.

        So ``valorRetIva = 0.00`` is simply a client that did not withhold, and
        there is nothing to reconcile. ``0.00`` is asserted both ways: it is
        written into the document, and it produces no finding at all.
        """
        invoice = self._create_sale()
        self.assertFalse(
            invoice.l10n_ec_withhold_ids,
            "the fixture must have no client-side withholding at all",
        )
        attachment, violations = self._wizard()._l10n_ec_run()
        root = etree.fromstring(self._xml_of(attachment).encode("utf-8"))
        rows = root.findall("ventas/detalleVentas")
        self.assertEqual(len(rows), 1)
        # The non-zero base the rule used to refuse, and the 0.00 it must file.
        self.assertNotEqual(rows[0].findtext("baseImpGrav"), "0.00")
        self.assertEqual(rows[0].findtext("valorRetIva"), "0.00")
        self.assertNotIn(
            "ventas.valor_ret_iva", {violation.rule for violation in violations}
        )
        from ..schema import validate_ats_xml

        self.assertTrue(validate_ats_xml(self._xml_of(attachment)).is_valid)

    # ------------------------------------------------------------------
    # The period field
    # ------------------------------------------------------------------

    def test_03_a_period_before_2000_is_refused_by_the_field(self):
        """The ficha's ``ESQUEMA`` says the year *"debe corresponder a periodos
        del 2000 en adelante"*. ATS-11 checks the header; this is the **field**
        refusing the input before anything is collected."""
        with self.assertRaises(ValidationError):
            self._wizard(period=(BEFORE_THE_CALENDAR, 3))
        with self.assertRaises(ValidationError):
            self._wizard(period=(CURRENT[0], 0))
        with self.assertRaises(ValidationError):
            self._wizard(period=(CURRENT[0], 13))
        # The boundary itself is accepted: 2000 is "the 2000 onward".
        wizard = self._wizard(period=(2000, 1))
        self.assertEqual(wizard.anio, 2000)

    def test_04_the_month_is_resolved_against_tabla_01_and_not_a_python_list(self):
        """``mes`` is an integer, and the ``Tabla 01`` row it must match is read
        from the catalog. A month the catalog does not publish stops generation
        rather than being formatted and filed."""
        self._create_bill()
        wizard = self._wizard()
        self.assertEqual(wizard._l10n_ec_period(), AtsPeriod(*CURRENT))
        self.assertEqual(wizard._l10n_ec_month_entry().code, f"{CURRENT[1]:02d}")
        # A month outside 1..12 is refused by the field constraint, so the
        # catalog read can never be asked about a code the table does not hold.
        for month in (0, 13):
            with self.assertRaises(ValidationError):
                self._wizard(period=(CURRENT[0], month))

    # ------------------------------------------------------------------
    # Negative path 1 -- a catalog gap
    # ------------------------------------------------------------------

    def test_05_a_catalog_gap_for_the_period_aborts_naming_table_code_and_window(self):
        """Negative path 1, reached with **shipped data and no mutation**.

        ``Tabla 13`` publishes the card payment forms from 2016-05-01 and
        2016-06-01, so form ``20`` has no window covering March 2016. A sale
        declaring that form is a lookup that returns zero entries, and zero is a
        coverage hole -- not a reason to emit the code anyway.

        The message is assembled by the wizard from the collector's report, so
        what it must carry is the three facts §5.6 Level 3 asks for: the **table**,
        the **code**, and the **window the lookup was for** -- plus what *was* in
        force that day, which is what tells a reader the lookup found nothing
        rather than found the wrong thing.
        """
        self._create_sale(
            sri_payment="l10n_ec.P20", posting_date=date(*BEFORE_CARD_FORMS, 10)
        )
        with self.assertRaises(UserError) as raised:
            self._wizard(period=BEFORE_CARD_FORMS).generate()
        message = str(raised.exception)
        # The table.
        self.assertIn("Tabla 13", message)
        # The code.
        self.assertIn("form 20", message)
        # The window: the reported day the lookup was made on.
        self.assertIn("01/03/2016", message)
        # And what it did find, so the reader is not left guessing.
        self.assertIn("Codes in force that day", message)
        self.assertNotIn("20,", message.split("Codes in force that day")[1][:40])

    def test_06_a_second_catalog_gap_is_reported_in_the_same_message(self):
        """Aggregation is the point of the single ``UserError``. Two unusable
        payment forms in one period must surface together, not one per run."""
        self._create_sale(
            sri_payment="l10n_ec.P20", posting_date=date(*BEFORE_CARD_FORMS, 10)
        )
        self._create_sale(
            sri_payment="l10n_ec.P16", posting_date=date(*BEFORE_CARD_FORMS, 11)
        )
        with self.assertRaises(UserError) as raised:
            self._wizard(period=BEFORE_CARD_FORMS).generate()
        message = str(raised.exception)
        self.assertIn("20", message)
        self.assertIn("16", message)

    # ------------------------------------------------------------------
    # Negative path 2 -- a catalog overlap
    # ------------------------------------------------------------------

    def test_07_a_catalog_overlap_for_the_period_aborts_naming_table_code_and_window(
        self,
    ):
        """Negative path 2.

        **How it is reached, and what that means.** The shipped catalog has no
        overlap -- that is what the Level 2 disjointness invariant asserts over
        every catalog entry and all 3149 rates, so an overlap in production data
        is a corruption a clean install cannot reach. The path is therefore
        reached by **adding** a second entry whose window covers a day an
        existing entry already claims, inside the test transaction. No shipped
        record is modified: the data files are untouched, the extra row rolls
        back with the test, and the condition being simulated is precisely the
        one the invariant exists to prevent.

        Simulating the failure is the only honest way to test the branch. A test
        written against the failure alone could pass for the wrong reason, so this
        one asserts the **cause** first: that before the extra entry the lookup
        returns exactly one, and after it returns two.

        ``Tabla 12`` is the table to corrupt because it is the one whose overlap
        the wizard's own preflight resolves -- ``resolve_regime`` counts the
        whole table, since a second regime would carry a different code and still
        be an overlap -- and its message is the one that renders the **windows**
        that are in conflict.
        """
        entry_model = self.env["l10n.ec.ats.catalog.entry"]
        table = self.env["l10n.ec.ats.catalog.table"].search([("code", "=", "12")])
        probe = date(*CURRENT, 31)

        def applicable():
            return entry_model._applicable_on(probe).filtered(
                lambda entry: entry.table_id == table
            )

        # The cause, asserted before the corruption is introduced.
        self.assertEqual(len(applicable()), 1)
        entry_model.create(
            {
                "table_id": table.id,
                "code": "12",
                "description": "OVERLAP TEST ENTRY",
                "percentage": 99.0,
                "date_start": date(CURRENT[0], 1, 1),
                "date_end": False,
            }
        )
        self.assertEqual(len(applicable()), 2)
        # And now the effect.
        self._create_bill()
        with self.assertRaises(UserError) as raised:
            self._wizard().generate()
        message = str(raised.exception)
        self.assertIn("Tabla 12", message)
        self.assertIn("one regime at a time", message)
        self.assertIn("2 entries were found", message)
        # The windows in conflict, not just the count.
        self.assertIn("..", message)
        self.assertIn("open", message)
        self.assertIn(f"{CURRENT[0]}-{CURRENT[1]:02d}", message)

    # ------------------------------------------------------------------
    # Negative path 3 -- an unresolved Tabla 3.10 rate
    # ------------------------------------------------------------------

    def test_08_an_unresolved_tabla_310_rate_aborts_naming_the_concept_and_window(self):
        """Negative path 3, reached with shipped data.

        ``Tabla 3.10`` gives concept ``302`` exactly one era, 2024-04-01 to
        2024-06-30, and in it the source cell states no single percentage. The
        rate is loaded ``unresolved`` with the cell verbatim in ``source_note``,
        and a period that needs it is refused: a rate invented to fill the cell
        would be indistinguishable from a real one in a filed return.

        ``income_tax_withholding_302`` ships with ``l10n_ec_code_ats = '352'``,
        a code no ``Tabla 3.10`` row states. Writing ``'302'`` onto it is what
        makes it the concept it is named after -- and it proves the pipeline
        follows the ATS code rather than the record's name.

        The **wizard's** preflight is what raises here rather than the
        collector, and the difference matters: the collector reports the
        unresolved cell and leaves the document out of the block, so a preflight
        reading the payload afterwards would find nothing left to check and would
        pass on exactly the period that cannot be filed. The preflight therefore
        reads the concepts off the **documents**, before collection drops
        anything, and its message names the window.
        """
        self.chart_template.ref("income_tax_withholding_302").write(
            {"l10n_ec_code_ats": "302"}
        )
        bill = self._create_bill(posting_date=date(*UNRESOLVED_AIR, 10))
        self._create_purchase_withholding(
            bill, self.chart_template.ref("income_tax_withholding_302")
        )
        with self.assertRaises(UserError) as raised:
            self._wizard(period=UNRESOLVED_AIR).generate()
        message = str(raised.exception)
        # The table, the code and the window.
        self.assertIn("Tabla 3.10", message)
        self.assertIn("concept 302", message)
        self.assertIn("2024-04-01..2024-06-30", message)
        self.assertIn("no single percentage", message)

    # ------------------------------------------------------------------
    # Negative path 4 -- missing source data
    # ------------------------------------------------------------------

    def test_09_missing_source_data_aborts_naming_the_record(self):
        """Negative path 4 and acceptance criterion 6.

        A vendor bill with no SRI authorization is the case the whole project is
        built around: nothing parses a vendor's XML yet, so the number is typed
        in, and a company that has not captured it cannot silently file an ATS
        with a fabricated one. Odoo Enterprise substitutes ``'9999999999'``;
        ATS stops.

        The error names the **document**, not the field alone -- somebody fixing
        a month of purchases has to know which bill.
        """
        bill = self._create_bill(authorization=False)
        self.assertFalse(bill.l10n_ec_authorization_number)
        with self.assertRaises(UserError) as raised:
            self._wizard().generate()
        message = str(raised.exception)
        self.assertIn("autorizacion", message)
        self.assertIn(bill.display_name, message)
        # The fabricated fallback this project refuses must appear nowhere.
        self.assertNotIn("9999999999", message)

    def test_10_the_reported_window_is_exactly_one_month(self):
        """The boundary is closed on both sides.

        ``fechaRegistro`` must equal the reported period, and an ATS covers one
        month, so the window handed to the collectors runs from the first day to
        the **real** last day -- ``AtsPeriod.last_day``, not day 31, because
        ``31/02`` is not a date -- and the day either side of it belongs to
        another period.
        """
        last_day = date(*CURRENT, 31)
        inside = self._create_bill(
            document_number="001-001-000000001", posting_date=last_day
        )
        outside = self._create_bill(
            document_number="001-001-000000002",
            posting_date=last_day + ONE_DAY,
        )
        self.assertNotEqual(inside.date, outside.date)
        attachment, _ = self._wizard()._l10n_ec_run()
        root = etree.fromstring(self._xml_of(attachment).encode("utf-8"))
        sequentials = [
            row.findtext("secuencial") for row in root.findall("compras/detalleCompras")
        ]
        self.assertEqual(sequentials, ["000000001"])

    # ------------------------------------------------------------------
    # Blocking versus warning
    # ------------------------------------------------------------------

    def test_11_a_blocking_violation_reaches_the_user(self):
        """A RUC whose module 11 check digit is wrong is a **grave** finding and
        stops generation. ``IdInformante`` is unconditional -- the ``Validaciones``
        cell states the RUC branch and no other.

        **Reached through the wizard, and that is the whole point of the
        assertion.** ``validators.validate_ats`` and ``builder.build_ats_xml``
        read the payload's header under different keys for a while, so the header
        arrived empty on the validator side and *every* rule in
        ``validate_header`` -- this one included -- evaluated against nothing and
        reported nothing. A caller papered over the gap by handing the validator a
        second view of the same dict, which meant the rule passed in isolation and
        was skipped in production. Both layers now go through
        :func:`~..builder.ats_header`, so the pipeline is the assertion: a direct
        validator call is not what is being protected here.
        """
        self._create_bill()
        self.company.partner_id.vat = RUC_BAD_CHECK_DIGIT
        with self.assertRaises(UserError) as raised:
            self._wizard().generate()
        message = str(raised.exception)
        self.assertIn("IdInformante", message)
        self.assertIn(RUC_BAD_CHECK_DIGIT, message)

    def test_11b_the_header_is_read_under_one_key_by_both_layers(self):
        """The contract itself, pinned so it cannot drift back.

        Three assertions, and the middle one is the one that catches a
        re-introduced alias: the wizard's own payload reaches the validator with
        **no** second ``iva`` key added, ``validate_ats`` still sees the header,
        and the document the builder renders is the same header. A caller that
        "fixed" the mismatch by reintroducing ``payload["iva"] = payload["header"]``
        would fail the second assertion, because the payload the builder is given
        would then carry a key it refuses.
        """
        from ..builder import ATS_HEADER_KEY, ats_header

        wizard = self._wizard()
        period = wizard._l10n_ec_period()
        self._create_bill()
        payload, problems = wizard._l10n_ec_payload(period)
        self.assertEqual(problems, [])
        # One key, and it is the one the builder owns.
        self.assertIn(ATS_HEADER_KEY, payload)
        self.assertNotIn(
            "iva",
            payload,
            "the wizard must not hand the builder a key it refuses as unknown",
        )
        # Both layers read the same mapping through the same accessor.
        self.assertIs(ats_header(payload), payload[ATS_HEADER_KEY])
        found = validate_ats(
            payload,
            period,
            env=self.env,
            air_codes=wizard._l10n_ec_air_codes(period),
        )
        self.assertEqual([str(v) for v in blocking(found)], [])
        # And the header really was walked: break it and the same payload reports.
        # The break is the same one ``test_11`` uses -- a RUC whose module 11 check
        # digit is wrong -- rather than an arbitrary string, because a value that
        # is not a RUC at all takes a different branch of ``validate_header``.
        payload[ATS_HEADER_KEY] = {
            **payload[ATS_HEADER_KEY],
            "IdInformante": RUC_BAD_CHECK_DIGIT,
        }
        self.assertIn(
            "identificacion.ruc",
            {
                violation.rule
                for violation in blocking(validate_ats(payload, period, env=self.env))
            },
        )

    def test_12_a_warning_alone_does_not_block_and_is_still_reported(self):
        """``ESQUEMA`` row 22 calls a ``montoIva`` that differs from
        ``baseImpGrav x porcentajeIva`` a *"mensaje de advertencia"*. Flattening
        the two severities would either block a file the SRI accepts or let one
        it refuses through.

        June 2016 is in the 14% regime and the tax under test is the 12% one, so
        the alert is real, produced by the loaded catalog, and does not stop the
        file.
        """
        self._create_bill(posting_date=date(*HISTORICAL, 10))
        wizard = self._wizard(period=HISTORICAL)
        attachment, violations = wizard._l10n_ec_run()
        rules = {violation.rule for violation in violations}
        self.assertIn("compras.monto_iva", rules)
        self.assertTrue(all(not v.blocking for v in violations), rules)
        self.assertEqual(attachment.name, HISTORICAL_ARCHIVE)

    def test_12b_a_warning_reaches_the_user_without_blocking_the_download(self):
        """The part ``generate()`` used to throw away.

        ``_l10n_ec_run()`` returns every violation precisely so a caller can
        report a non-blocking finding, and ``generate()`` discarded the second
        element of that tuple. The computation was real and the result was
        dropped on the floor, which is indistinguishable from the check never
        having run.

        So an *alerta* has to be **readable** and the file still has to download.
        ``UserError`` is not available for it -- the SRI accepts the file, and an
        exception would make an acceptable return unfileable -- and Odoo 19 has no
        non-raising user-facing exception to use instead. The channel is
        :attr:`L10nEcAtsGenerate.warnings`, which the form renders.
        """
        self._create_bill(posting_date=date(*HISTORICAL, 10))
        wizard = self._wizard(period=HISTORICAL)
        # The warning is really there before the button runs.
        _attachment, violations = wizard._l10n_ec_run()
        self.assertTrue(warnings_of(violations))

        action = wizard.generate()
        # Non-blocking: the download action comes back and names the file.
        self.assertEqual(action["type"], "ir.actions.act_url")
        attachment_id = int(action["url"].split("/web/content/")[1].split("?")[0])
        self.assertEqual(
            self.env["ir.attachment"].browse(attachment_id).name, HISTORICAL_ARCHIVE
        )
        # And the finding is in the wizard, in the reader's terms.
        report = wizard.warnings
        self.assertTrue(report)
        self.assertIn("did not stop this file", report)
        self.assertIn("compras.monto_iva", report)
        self.assertIn("montoIva", report)

    def test_12c_a_clean_period_reports_no_warnings_at_all(self):
        """``False`` and not an empty string: an empty box reads as *"something
        was found and it rendered blank"*, which is the ambiguity this field
        exists to remove."""
        self._create_bill()
        wizard = self._wizard()
        wizard.generate()
        self.assertFalse(wizard.warnings)

    # ------------------------------------------------------------------
    # Criterion 8 -- temporal resolution is real
    # ------------------------------------------------------------------

    def test_historical_period_files_a_different_document(self):
        """Acceptance criterion 8, and the strongest test in the plan.

        One withholding concept, one tax, one base, two periods. ``Tabla 3.10``
        states concept ``304`` at **8%** through the 2016 era and at **10%** from
        2024-03-01, and ``porcentajeAir`` is read from the catalog for the
        reported period -- while ``valRetAir`` comes from the withholding
        record and is therefore **identical** in both files.
        So the two documents differ in exactly one catalog value, and the only
        thing that can produce it is the date in the lookup. Drop ``period`` from
        that lookup and the two ``porcentajeAir`` values become the same number
        while every other test in this suite still passes.

        Each period gets its own bill and its own withholding -- a withholding is
        dated, and a single one cannot sit in two months -- but the **tax**, the
        **product** and therefore the base and the withheld amount are the same,
        which is what makes the comparison about the rate and nothing else.
        """
        historical_bill = self._create_bill(
            document_number="001-001-000000101", posting_date=date(*HISTORICAL, 10)
        )
        self._create_purchase_withholding(historical_bill, self.tax_air_304)
        current_bill = self._create_bill(
            document_number="001-001-000000202", posting_date=date(*CURRENT, 10)
        )
        self._create_purchase_withholding(current_bill, self.tax_air_304)
        self.assertEqual(
            abs(historical_bill.amount_untaxed_signed),
            abs(current_bill.amount_untaxed_signed),
        )

        historical_attachment, _ = self._wizard(period=HISTORICAL)._l10n_ec_run()
        historical_xml = self._xml_of(historical_attachment)
        current_attachment, _ = self._wizard(period=CURRENT)._l10n_ec_run()
        current_xml = self._xml_of(current_attachment)

        def field(xml_string, name):
            root = etree.fromstring(xml_string.encode("utf-8"))
            return root.findtext(f"compras/detalleCompras/air/detalleAir/{name}")

        # Both periods carried the same concept, at the catalog's own rates.
        self.assertEqual(field(historical_xml, "codRetAir"), "304")
        self.assertEqual(field(historical_xml, "porcentajeAir"), "8.00")
        self.assertEqual(field(current_xml, "codRetAir"), "304")
        self.assertEqual(field(current_xml, "porcentajeAir"), "10.00")
        # The record-derived amounts did not move, which is what proves the
        # difference is the catalog and not the fixture.
        self.assertEqual(
            field(historical_xml, "baseImpAir"), field(current_xml, "baseImpAir")
        )
        self.assertEqual(
            field(historical_xml, "valRetAir"), field(current_xml, "valRetAir")
        )
        # And the documents are genuinely different files.
        self.assertNotEqual(historical_xml, current_xml)
        self.assertEqual(historical_attachment.name, HISTORICAL_ARCHIVE)
        self.assertEqual(current_attachment.name, CURRENT_ARCHIVE)
        # Both still satisfy the schema.
        from ..schema import validate_ats_xml

        self.assertTrue(validate_ats_xml(historical_xml).is_valid)
        self.assertTrue(validate_ats_xml(current_xml).is_valid)

    # ------------------------------------------------------------------
    # The AirConditionalCodes seam
    # ------------------------------------------------------------------

    def test_the_air_seam_is_populated_for_the_period_and_accepts_a_dividend_row(self):
        """The seam ATS-11 left open, closed from the catalog.

        ``validators.validate_compras_row`` **raises** ``ValueError`` when an
        ``air`` row carries one of the five conditional elements and the caller
        supplied no ``AirConditionalCodes``. The SRI catalog carries no column
        saying which ``codRetAir`` needs which sub-report, and it cannot be
        derived: ``338`` is *Compra local de banano a productor* in 2016 and
        *Producción y venta local de banano* from 2020. So the grouping is
        **era-scoped data**, and the wizard resolves it for the reported period.

        This asserts the resolution is populated, that it is era-correct, and
        that a dividend row carrying the dividend elements passes validation.
        """
        wizard = self._wizard()
        codes = wizard._l10n_ec_air_codes(wizard._l10n_ec_period())
        self.assertTrue(codes.dividend, "the dividend group resolved empty")
        self.assertTrue(codes.banana, "the banana group resolved empty")
        # Group **names**, never codes: the field holds no SRI code.
        from ..validators import DIVIDEND_ELEMENTS, AirConditionalCodes

        self.assertIsInstance(codes, AirConditionalCodes)
        self.assertEqual(
            set(codes.groups().values()),
            {"dividend", "banana"},
        )
        # Concept 504A is *Dividendos a sociedades* in the 2025-09 era, which is
        # the only stretch where the SRI also states a percentage for it.
        self.assertIn("504A", codes.dividend)
        self.assertTrue(set(codes.dividend).isdisjoint(codes.banana))
        self.assertEqual(
            set(DIVIDEND_ELEMENTS), {"fechaPagoDiv", "imRentaSoc", "anioUtDiv"}
        )

        # A dividend row: the air entry carries the dividend elements and the
        # code is one the catalog groups as dividend for this period.
        row = {
            "tpIdProv": "01",
            "idProv": RUC_VALID,
            "tipoComprobante": "01",
            "fechaRegistro": "03/08/2026",
            "fechaEmision": "03/08/2026",
            "establecimiento": "001",
            "puntoEmision": "001",
            "secuential": "000000123",
            "autorizacion": "123456789012",
            "codSustento": "01",
            "baseImpGrav": "100.00",
            "montoIva": "12.00",
            "air": [
                {
                    "codRetAir": "504A",
                    "baseImpAir": "100.00",
                    "porcentajeAir": "12.00",
                    "valRetAir": "12.00",
                    "fechaPagoDiv": "15/08/2026",
                    "imRentaSoc": "1.20",
                    "anioUtDiv": "2026",
                }
            ],
            "formasDePago": [{"formaPago": "01"}],
        }
        from ..validators import validate_compras_row

        violations = validate_compras_row(
            row, AtsPeriod(*CURRENT), reader=_reader(self.env), air_codes=codes
        )
        self.assertEqual([str(violation) for violation in violations], [])

    def test_the_air_seam_refuses_a_banana_element_on_a_dividend_code(self):
        """The negative twin: the seam is what makes the rule enforceable at
        all. Without it ``validate_compras_row`` raises ``ValueError``; with it
        the mismatch is a named violation carrying the code.

        ``504A`` is *Dividendos a sociedades* in the 2025-09 era and therefore in
        the **dividend** group, so the two banana elements must be refused on it.
        """
        from ..validators import validate_compras_row

        wizard = self._wizard()
        codes = wizard._l10n_ec_air_codes(wizard._l10n_ec_period())
        self.assertIn("504A", codes.dividend)
        row = {
            "tpIdProv": "01",
            "idProv": RUC_VALID,
            "tipoComprobante": "01",
            "fechaRegistro": "03/08/2026",
            "fechaEmision": "03/08/2026",
            "establecimiento": "001",
            "puntoEmision": "001",
            "secuencial": "000000123",
            "autorizacion": "123456789012",
            "codSustento": "01",
            "baseImpGrav": "100.00",
            "montoIva": "12.00",
            "air": [
                {
                    "codRetAir": "504A",
                    "baseImpAir": "100.00",
                    "porcentajeAir": "12.00",
                    "valRetAir": "12.00",
                    "numCajBan": "10",
                    "precCajBan": "20.00",
                }
            ],
            "formasDePago": [{"formaPago": "01"}],
        }
        violations = validate_compras_row(
            row, AtsPeriod(*CURRENT), reader=_reader(self.env), air_codes=codes
        )
        self.assertIn(
            "air.emision_condicional", {violation.rule for violation in violations}
        )

    def test_the_air_grouping_is_era_scoped_and_not_a_blanket_code_list(self):
        """Why ``detail_group`` lives on the **rate** and not on the concept.

        Code ``340`` is *Otras retenciones aplicables el 1%* through 2014 and
        *Impuesto único a la exportación de banano* from 2015. A concept-level
        grouping would file a 2013 banana sub-report against a concept that was
        not a banana concept then, and would file no sub-report at all for the
        2013 concept that actually needed one. So the same code is banana in one
        period and in no group at all in another.
        """
        wizard = self._wizard()
        banana_2016 = wizard._l10n_ec_air_codes(AtsPeriod(2016, 6)).banana
        banana_2013 = wizard._l10n_ec_air_codes(AtsPeriod(2013, 6)).banana
        self.assertIn("340", banana_2016)
        self.assertNotIn("340", banana_2013)
        # The same holds for a code whose era hole the SRI itself created:
        # 341 is a banana concept from 2015 to 2019 and was dropped afterwards.
        self.assertIn("341", wizard._l10n_ec_air_codes(AtsPeriod(2016, 6)).banana)
        self.assertNotIn("341", wizard._l10n_ec_air_codes(AtsPeriod(2026, 8)).banana)
        # And the rate table carries only group **names**, never a code.
        rates = self.env["l10n.ec.ats.income.withholding.rate"]
        groups = {key for key, _label in rates._fields["detail_group"].selection}
        self.assertEqual(groups, {"dividend", "banana"})
        self.assertTrue(
            all(not rate.detail_group or rate.detail_group in groups for rate in rates)
        )

    # ------------------------------------------------------------------
    # Access
    # ------------------------------------------------------------------

    def test_a_retention_share_with_no_window_joins_the_same_message(self):
        """A **late** catalog gap, found by the business layer rather than the
        preflight, aggregates the same way.

        ``Tabla 11`` codes ``9`` and ``10`` -- the shares of ``valRetBien10`` and
        ``valRetServ20`` -- start on 2015-06-01, so March 2015 has no window for
        them. The preflight resolves the *table* (codes ``1``, ``2``, ``3`` and
        ``11`` do cover that month) and passes; the per-element lookup inside
        ``validate_compras_row`` is the one that cannot be answered, and it has
        to arrive as a named problem rather than a ``ValueError`` from four
        layers down.

        The payload is the wizard's own, collected for that month, with the one
        element the rules cannot resolve added: a rate a company did withhold
        has to be filed, so the row has to carry it.
        """
        wizard = self._wizard(period=BEFORE_TABLA11_SHARES)
        self._create_bill(posting_date=date(*BEFORE_TABLA11_SHARES, 10))
        period = wizard._l10n_ec_period()
        payload, problems = wizard._l10n_ec_payload(period)
        self.assertEqual(problems, [])
        payload["compras"][0]["valRetBien10"] = 1.2
        _violations, problems = wizard._l10n_ec_validation(
            payload, period, wizard._l10n_ec_air_codes(period)
        )
        rendered = "\n".join(problems)
        self.assertIn("11", rendered)
        self.assertIn("9", rendered)
        self.assertIn("2015-03", rendered)

    def test_the_air_seam_resolves_exactly_the_codes_the_catalog_publishes(self):
        """The ``_applicable_on`` trap, asserted on its result.

        ``l10n.ec.temporal._applicable_on`` is ``@api.model`` and its ``search``
        does not preserve the calling recordset's domain, so resolving against a
        scoped recordset re-searches the **whole model**. That failure is silent
        and enormous: it would hand back all 414 concepts and all 3149 rates, and
        every ``codRetAir`` would look like a dividend and a banana one at once.

        So the assertion is on the **exact** sets, not on membership. For
        2026-08 the SRI publishes three dividend concepts and two banana ones --
        ``330``, ``341`` and ``342`` were dropped by the SRI itself and have no
        era covering the day -- and a domain-losing read could not land on 3 and
        2 by accident.
        """
        wizard = self._wizard()
        codes = wizard._l10n_ec_air_codes(AtsPeriod(*CURRENT))
        self.assertEqual(
            codes.dividend,
            frozenset({"327", "504A", "504D"}),
        )
        self.assertEqual(
            codes.banana,
            frozenset({"338", "340"}),
        )

    def test_a_refused_period_produces_no_attachment(self):
        """Nothing is packaged until both validation layers have passed.

        The temptation when a wizard collects problems is to attach the file
        anyway and report the problems alongside it, so the user can see what
        nearly shipped. That would be filing something the SRI refuses, and an
        attachment is a file a user can download and send without reading the
        error, so the check belongs here: a refused period leaves **no**
        attachment behind, with that name.
        """
        self._create_bill(authorization=False)
        domain = [("name", "=", CURRENT_ARCHIVE)]
        before = self.env["ir.attachment"].search_count(domain)
        with self.assertRaises(UserError):
            self._wizard().generate()
        self.assertEqual(self.env["ir.attachment"].search_count(domain), before)

    def test_13a_the_wizard_is_reachable_from_a_form_and_a_menu(self):
        """A wizard nobody can open is a wizard nobody has proved works.

        Asserted through the registry rather than by reading the XML, because
        that is what actually has to be true: the form resolves against this
        model, the action points at it, and the menu hangs off the SRI root the
        sibling EDI addon uses. A view that fails to compile raises at install, so
        ``get_view`` succeeding is already a strong assertion -- and it is the one
        that would catch a ``warnings`` field referenced by the arch but absent
        from the model, or a rename that left the menu dangling.
        """
        view = self.env["l10n.ec.ats.generate"].get_view(
            self.env.ref("l10n_ec_ats.l10n_ec_ats_generate_view_form").id,
            "form",
        )
        arch = view["arch"]
        for field in ("company_id", "anio", "mes", "warnings"):
            self.assertIn(f'name="{field}"', arch, field)
        self.assertIn('name="generate"', arch)
        action = self.env.ref("l10n_ec_ats.l10n_ec_ats_generate_action")
        self.assertEqual(action.res_model, "l10n.ec.ats.generate")
        self.assertEqual(action.view_id._name, "ir.ui.view")
        self.assertEqual(action.view_id.model, "l10n.ec.ats.generate")
        menu = self.env.ref("l10n_ec_ats.l10n_ec_ats_generate_menu")
        self.assertEqual(menu.action, action)
        # Under the SRI root, which is where a person filing to the SRI looks.
        self.assertEqual(menu.parent_id, self.env.ref("l10n_ec.sri_menu"))

    def test_13_a_group_user_may_run_the_wizard(self):
        """ACL: an accountant with the base user group creates the wizard, sets
        the period and generates. Without the row in
        ``ir.model.access.csv`` the very first call is an ``AccessError``, and
        the file could only ever be produced from a shell."""
        wizard_user = (
            self.env["res.users"]
            .with_context(no_reset_password=True)
            .create(
                {
                    "name": "ATS accountant",
                    "login": "ats_accountant",
                    # An accountant who files returns: the base user group
                    # alone cannot read a journal entry, and neither can the
                    # wizard's ACL grant it. Both are needed, which is exactly
                    # why the ACL row is only half the access story.
                    "group_ids": [
                        (
                            6,
                            0,
                            [
                                self.env.ref("base.group_user").id,
                                self.env.ref("account.group_account_invoice").id,
                            ],
                        )
                    ],
                    "company_id": self.company.id,
                    "company_ids": [(6, 0, [self.company.id])],
                }
            )
        )
        self._create_bill()
        wizard = (
            self.env["l10n.ec.ats.generate"]
            .with_user(wizard_user)
            .with_context(active_model="l10n.ec.ats.generate")
            .create(
                {
                    "company_id": self.company.id,
                    "anio": CURRENT[0],
                    "mes": CURRENT[1],
                }
            )
        )
        attachment, _ = wizard._l10n_ec_run()
        self.assertEqual(attachment.name, CURRENT_ARCHIVE)


def _reader(env):
    """A :class:`~..validators.CatalogReader` for a test env."""
    from ..validators import CatalogReader

    return CatalogReader(env)
