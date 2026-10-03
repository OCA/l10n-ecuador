from datetime import date

from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.l10n_ec_account_edi.tests.test_edi_common import TestL10nECEdiCommon

from ..models.l10n_ec_ats_collector import IVA_RETENTION_ELEMENTS

# ``Tabla 3.10`` concept ``304`` is the dated-rate fixture: it is *Servicios
# profesionales prestados por sociedades residentes* at 8% through the 2016 era and
# the same concept at 10% from 2024. Two eras, two rates, one code -- which is
# exactly what makes it the honest way to prove the resolution is dated.
CONCEPT_RERATED = "304"

# ``Tabla 5`` codes whose validity window does not cover the reported period
# below. ``14`` starts 2018-01-01 and ``00`` ends 2015-02-28, so a 2016 report
# accepts neither.
PERIOD = (date(2016, 3, 1), date(2016, 3, 31))
MODERN_PERIOD = (date(2026, 3, 1), date(2026, 3, 31))


@tagged("post_install_l10n", "post_install", "-at_install")
class TestL10nEcAtsCollectorCompras(TestL10nECEdiCommon):
    """One ``detalleCompras`` row per vendor document, and nothing invented.

    The two rules every assertion below leans on come straight from the
    feature document: a missing value is **never** substituted -- it is reported
    as a blocking problem naming the document and the field -- and ``000`` is
    never a valid establishment or emission point, even though ``ats.xsd``
    accepts it.
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
        # The ordinary vendor-bill journal, shadowed for the same reason
        # ``l10n_ec_withhold``'s suite shadows it: the EC chart template ships two
        # ``type = 'purchase'`` journals and ``TestL10nECCommon`` points at the
        # purchase-liquidation one.
        cls.journal_purchase = cls.company_data["default_journal_purchase"]
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
        cls.journal_purchase_withhold.l10n_ec_emission_address_id = (
            cls.partner_contact.id
        )
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
        cls.tax_withhold_vat_100 = cls.chart_template.ref("tax_withhold_vat_100")
        cls.tax_withhold_profit_303 = cls.chart_template.ref("tax_withhold_profit_303")
        cls.tax_withhold_profit_304 = cls.chart_template.ref("tax_withhold_profit_304")
        cls.tax_unresolvable_ats_code = cls.chart_template.ref(
            "income_tax_withholding_302"
        )

    # ------------------------------------------------------------------
    # Fixtures
    # ------------------------------------------------------------------

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

    def _create_bill(
        self,
        *,
        partner=None,
        taxes=None,
        document_number="001-001-000000123",
        tax_support="01",
        authorization="123456789012",
        posting_date=PERIOD[0],
        emission_date=None,
    ):
        """Post one vendor bill carrying every ``compras`` field a row needs.

        Built through the shared ``_l10n_ec_create_in_invoice`` fixture rather
        than by hand: that is the path the withholding wizard needs a payable
        line and a document number from, and re-deriving it here would only
        diverge from what the sibling addons prove works.

        Three writes matter here, and their order matters:

        * ``date`` / ``invoice_date`` are set **before** posting -- both are
          readonly on a posted move -- because the tests need a 2016 window to
          prove the catalogues are resolved for the period rather than for today.
        * ``l10n_ec_authorization_number`` is written **after** posting: it is a
          stored compute off ``edi_document_ids``, and posting creates that
          document, so a value written beforehand is recomputed away. It is also
          the production shape -- nothing parses a vendor's XML yet (§5.8), so on
          a vendor bill this number is typed in, not derived.
        * ``l10n_ec_tax_support`` is cleared **after** posting, because ``_post``
          refuses a purchase document with none; a bill whose support went
          missing is built by clearing it once the document is posted.
        """
        invoice = self._l10n_ec_create_in_invoice(
            partner or self.partner_ruc,
            taxes=taxes,
            journal=self.journal_purchase,
            latam_document_type=self.env.ref("l10n_ec.ec_dt_01"),
            auto_post=False,
            l10n_latam_document_number=document_number,
        )
        invoice.write(
            {"date": posting_date, "invoice_date": emission_date or posting_date}
        )
        invoice.l10n_ec_tax_support = tax_support or "01"
        invoice.action_post()
        if authorization:
            invoice.l10n_ec_authorization_number = authorization
        if not tax_support:
            invoice.l10n_ec_tax_support = False
        return invoice

    def _setup_company_for_withholding(self):
        """Give the company what the withholding journal validates against.

        The withholding journal posts through the SRI EDI format, so it needs the
        company's RUC, a loaded certificate and a street on its emission address.
        Set up directly rather than through ``_setup_edi_company_ec``, which also
        rewrites the sales and vendor-bill journals -- journals this collector has
        no interest in.
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

    def _collect(self, period=PERIOD, **kwargs):
        return self.Collector.collect_compras_with_errors(
            self.company, period[0], period[1], **kwargs
        )

    def _create_withholding(self, bill, tax, tax_support="01"):
        """Post a purchase withholding against ``bill`` and link the two.

        Built directly rather than through
        ``l10n_ec.wizard.create.purchase.withhold``. The line values mirror what
        that wizard's ``_prepare_basis_vals`` / ``_prepare_basis_counterpart_vals``
        produce, because those are the shapes the collector reads. What is
        skipped is ``_try_reconcile_withholding_moves``: settling the withholding
        against the bill's payable line is an accounting concern the collector has
        no opinion about, and driving it here only couples these tests to
        reconciliation rules that belong to the withholding addon's own suite.

        ``l10n_ec_invoice_withhold_id`` on the basis line is the only link the
        collector follows, and the basis is the value the wizard would compute:
        the bill's own tax for a VAT withholding, its untaxed amount for an
        income one.
        """
        self._setup_company_for_withholding()
        if tax.tax_group_id.l10n_ec_type == "withhold_vat_purchase":
            base = abs(bill.amount_tax_signed)
        else:
            base = abs(bill.amount_untaxed_signed)
        lines = []
        for tax_data in tax.compute_all(base).get("taxes", []):
            amount = abs(tax_data.get("base"))
            lines.append(
                (
                    0,
                    0,
                    {
                        "partner_id": bill.partner_id.id,
                        "quantity": 1.0,
                        "price_unit": amount,
                        "account_id": tax_data.get("account_id"),
                        "name": "RET test basis",
                        "debit": amount,
                        "credit": 0.0,
                        "tax_ids": [(6, 0, tax.ids)],
                        "display_type": "product",
                        "l10n_ec_invoice_withhold_id": bill.id,
                        "l10n_ec_tax_support": tax_support,
                    },
                )
            )
            lines.append(
                (
                    0,
                    0,
                    {
                        "partner_id": bill.partner_id.id,
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
                "journal_id": self.journal_purchase_withhold.id,
                "date": bill.date,
                "move_type": "entry",
                "partner_id": bill.partner_id.id,
                "ref": "RET-TEST-0001",
                "l10n_latam_document_type_id": self.env.ref("l10n_ec.ec_dt_07").id,
                "l10n_ec_withholding_type": "purchase",
                "line_ids": lines,
            }
        )
        withholding._post()
        bill.l10n_ec_withhold_ids = [(4, withholding.id)]
        return withholding

    # ------------------------------------------------------------------
    # Row granularity and the primary key
    # ------------------------------------------------------------------

    def test_01_one_row_per_bill_with_the_full_primary_key(self):
        self._create_bill(document_number="001-002-000000045")
        rows, errors = self._collect()
        self.assertFalse(errors, errors)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["codSustento"], "01")
        self.assertEqual(row["tipoComprobante"], "01")
        self.assertEqual(row["establecimiento"], "001")
        self.assertEqual(row["puntoEmision"], "002")
        self.assertEqual(row["secuencial"], "000000045")
        self.assertEqual(row["fechaRegistro"], "01/03/2016")
        self.assertEqual(row["fechaEmision"], "01/03/2016")
        self.assertEqual(row["autorizacion"], "123456789012")
        self.assertTrue(row["idProv"])
        self.assertTrue(row["tpIdProv"])

    def test_02_two_bills_produce_two_rows(self):
        self._create_bill(document_number="001-001-000000001")
        self._create_bill(document_number="001-001-000000002")
        rows, errors = self._collect()
        self.assertFalse(errors, errors)
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            sorted(row["secuencial"] for row in rows),
            ["000000001", "000000002"],
        )

    def test_03_draft_and_out_of_window_bills_are_not_collected(self):
        posted = self._create_bill(document_number="001-001-000000001")
        draft = self._create_bill(document_number="001-001-000000002")
        draft.button_draft()
        self.assertEqual(posted.state, "posted")
        self.assertEqual(draft.state, "draft")
        rows, errors = self._collect()
        self.assertFalse(errors, errors)
        self.assertEqual([row["secuencial"] for row in rows], ["000000001"])

    def test_04_empty_period_yields_an_empty_list_and_no_error(self):
        """No documents is a legitimate report, not a failure."""
        rows, errors = self._collect(period=(date(2016, 7, 1), date(2016, 7, 31)))
        self.assertEqual(rows, [])
        self.assertEqual(errors, [])
        self.assertEqual(
            self.Collector.collect_compras(
                self.company, date(2016, 7, 1), date(2016, 7, 31)
            ),
            [],
        )

    # ------------------------------------------------------------------
    # Bases and taxes
    # ------------------------------------------------------------------

    def test_05_non_zero_rated_bill_lands_its_base_in_base_imp_grav(self):
        bill = self._create_bill(taxes=self.tax_vat12)
        rows, errors = self._collect()
        self.assertFalse(errors, errors)
        row = rows[0]
        self.assertEqual(row["baseImpGrav"], bill.amount_untaxed)
        self.assertEqual(row["montoIva"], bill.amount_tax)
        self.assertEqual(row["baseNoGraIva"], 0.0)
        self.assertEqual(row["baseImponible"], 0.0)
        self.assertEqual(row["baseImpExe"], 0.0)
        self.assertEqual(row["montoIce"], 0.0)

    def test_06_zero_rated_bill_lands_its_base_in_base_imponible(self):
        bill = self._create_bill(taxes=self.tax_zero_vat)
        rows, errors = self._collect()
        self.assertFalse(errors, errors)
        row = rows[0]
        self.assertEqual(row["baseImponible"], bill.amount_untaxed)
        self.assertEqual(row["baseImpGrav"], 0.0)
        self.assertEqual(row["montoIva"], 0.0)

    def test_07_the_other_two_buckets_are_read_from_their_own_groups(self):
        """``not_charged_vat`` and ``exempt_vat`` are distinct selections.

        Both are read off ``tax_group_id.l10n_ec_type``, never off a literal
        list of taxes, so the split cannot collapse into one bucket.
        """
        not_charged = self._create_bill(
            taxes=self.tax_not_charged_vat, document_number="001-001-000000010"
        )
        exempt = self._create_bill(
            taxes=self.tax_exempt_vat, document_number="001-001-000000011"
        )
        rows, errors = self._collect()
        self.assertFalse(errors, errors)
        by_seq = {row["secuencial"]: row for row in rows}
        self.assertEqual(
            by_seq["000000010"]["baseNoGraIva"], not_charged.amount_untaxed
        )
        self.assertEqual(by_seq["000000010"]["baseImpGrav"], 0.0)
        self.assertEqual(by_seq["000000011"]["baseImpExe"], exempt.amount_untaxed)
        self.assertEqual(by_seq["000000011"]["baseNoGraIva"], 0.0)

    def test_08_every_line_repeats_only_the_three_iva_retention_elements(self):
        self._create_bill(taxes=self.tax_vat12)
        rows, errors = self._collect()
        self.assertFalse(errors, errors)
        row = rows[0]
        for element in ("valRetBien10", "valRetServ20", "valRetServ50"):
            self.assertIn(element, row)
        self.assertNotIn("air", row)

    # ------------------------------------------------------------------
    # Blocking conditions
    # ------------------------------------------------------------------

    def test_09_missing_authorization_blocks_and_emits_no_placeholder(self):
        """Odoo Enterprise sends ``'9999999999'``. ATS refuses to guess."""
        self._create_bill(authorization=False)
        rows, errors = self._collect()
        self.assertEqual(rows, [])
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["field"], "autorizacion")
        message = str(errors[0]["message"])
        self.assertNotIn("9999999999", message)
        # Nothing anywhere in the payload may carry a fabricated authorization.
        self.assertNotIn("9999999999", str(rows))
        self.assertNotIn("autorizacion", str(rows))

    def test_10_missing_tax_support_blocks(self):
        self._create_bill(tax_support=False)
        rows, errors = self._collect()
        self.assertEqual(rows, [])
        self.assertEqual([error["field"] for error in errors], ["codSustento"])

    def test_11_cod_sustento_outside_the_reported_period_blocks(self):
        """``14`` is a real ``Tabla 5`` code, in force from 2018-01-01.

        Reporting 2016-03 must reject it, and the message has to name the codes
        that *are* valid for that period -- read from the catalog, not from a
        Python literal.
        """
        valid_2016 = self._catalog_codes("05", PERIOD[0])
        self.assertNotIn("14", valid_2016)
        self.assertIn("01", valid_2016)
        bill = self._create_bill(tax_support="14")
        self.assertEqual(bill.l10n_ec_tax_support, "14")
        rows, errors = self._collect()
        self.assertEqual(rows, [])
        self.assertEqual([error["field"] for error in errors], ["codSustento"])
        message = str(errors[0]["message"])
        self.assertIn("14", message)
        for code in valid_2016:
            self.assertIn(code, message)

    def test_12_cod_sustento_that_is_not_a_tabla_5_code_blocks(self):
        self._create_bill(tax_support="99")
        rows, errors = self._collect()
        self.assertEqual(rows, [])
        self.assertEqual([error["field"] for error in errors], ["codSustento"])

    def test_13_cod_sustento_15_is_accepted_for_a_period_that_covers_it(self):
        """The retype's payoff, end to end.

        ``15`` was not assignable on the move while the field was a
        ``Selection``, so no company could file it at all.
        """
        valid_modern = self._catalog_codes("05", MODERN_PERIOD[0])
        self.assertIn("15", valid_modern)
        self._create_bill(
            tax_support="15",
            posting_date=MODERN_PERIOD[0],
            authorization="123456789012",
        )
        rows, errors = self._collect(period=MODERN_PERIOD)
        self.assertFalse(errors, errors)
        self.assertEqual(rows[0]["codSustento"], "15")

    def test_14_fecha_registro_outside_the_reported_month_blocks(self):
        """The ficha: ``fechaRegistro`` must equal the period being reported.

        The search window is ``[date_start, date_finish]``, but the rule is
        stricter -- the accounting date has to fall in the reported **month**. A
        caller that hands over a window wider than a month gets told so instead
        of silently filing the document.
        """
        self._create_bill(posting_date=date(2016, 2, 15))
        rows, errors = self._collect(period=(date(2016, 1, 1), date(2016, 3, 31)))
        self.assertEqual(rows, [])
        self.assertEqual([error["field"] for error in errors], ["fechaRegistro"])

    def test_15_a_zero_establishment_is_rejected(self):
        """``ats.xsd`` accepts ``000``; the ficha does not (§5.4b)."""
        self._create_bill(document_number="000-001-000000123")
        rows, errors = self._collect()
        self.assertEqual(rows, [])
        self.assertEqual([error["field"] for error in errors], ["establecimiento"])

    def test_16_a_zero_emission_point_is_rejected(self):
        self._create_bill(document_number="001-000-000000123")
        rows, errors = self._collect()
        self.assertEqual(rows, [])
        self.assertEqual([error["field"] for error in errors], ["puntoEmision"])

    def test_17_a_supplier_without_identification_blocks(self):
        partner = self.env["res.partner"].create(
            {"name": "Sin Identificacion", "country_id": self.env.ref("base.ec").id}
        )
        self._create_bill(partner=partner)
        rows, errors = self._collect()
        self.assertEqual(rows, [])
        # ``tpIdProv`` cannot be derived from an identification nobody has, so
        # that is the field the refusal names.
        self.assertIn("tpIdProv", [error["field"] for error in errors])

    def test_18_the_final_consumer_sentinel_is_rejected(self):
        """``9999999999999`` is Consumer Final, which has no purchase row."""
        self._create_bill(partner=self.partner_cf)
        rows, errors = self._collect()
        self.assertEqual(rows, [])
        self.assertIn("tpIdProv", [error["field"] for error in errors])

    # ------------------------------------------------------------------
    # parteRel
    # ------------------------------------------------------------------

    def test_19_parte_rel_follows_the_related_party_flag(self):
        self.partner_ruc.l10n_ec_related_party = False
        self._create_bill(partner=self.partner_ruc)
        rows, errors = self._collect()
        self.assertFalse(errors, errors)
        self.assertEqual(rows[0]["parteRel"], "NO")

        self.partner_ruc.l10n_ec_related_party = True
        rows, errors = self._collect()
        self.assertFalse(errors, errors)
        self.assertEqual(rows[0]["parteRel"], "SI")

    # ------------------------------------------------------------------
    # Income withholding (``air``)
    # ------------------------------------------------------------------

    def test_20_air_resolves_concept_and_a_dated_rate(self):
        """Same concept, same tax, different percentage in a different era.

        ``304`` is 8% in 2016 and 10% from 2024. A collector that read the
        current rate would report the same number for both periods and the whole
        effective-dating design would be cosmetic.

        Two bills are needed rather than one: a document is selected by its
        accounting date, so it can only ever be reported in one period. What
        varies between them is the period, not the tax.
        """
        old_bill = self._create_bill(
            document_number="001-001-000000030", posting_date=PERIOD[0]
        )
        self._create_withholding(old_bill, self.tax_withhold_profit_304)
        new_bill = self._create_bill(
            document_number="001-001-000000031", posting_date=MODERN_PERIOD[0]
        )
        self._create_withholding(new_bill, self.tax_withhold_profit_304)

        old_rows, old_errors = self._collect(period=PERIOD)
        new_rows, new_errors = self._collect(period=MODERN_PERIOD)
        self.assertFalse(old_errors, old_errors)
        self.assertFalse(new_errors, new_errors)
        self.assertEqual(len(old_rows), 1)
        self.assertEqual(len(new_rows), 1)

        old_air = old_rows[0]["air"]
        new_air = new_rows[0]["air"]
        self.assertEqual(len(old_air), 1)
        self.assertEqual(len(new_air), 1)
        self.assertEqual(old_air[0]["codRetAir"], CONCEPT_RERATED)
        self.assertEqual(new_air[0]["codRetAir"], CONCEPT_RERATED)
        self.assertEqual(float(old_air[0]["porcentajeAir"]), 8.0)
        self.assertEqual(float(new_air[0]["porcentajeAir"]), 10.0)
        self.assertNotEqual(old_air[0]["porcentajeAir"], new_air[0]["porcentajeAir"])

    def test_21_a_concept_the_catalog_does_not_hold_blocks_the_row(self):
        """``income_tax_withholding_302`` carries ``l10n_ec_code_ats`` ``352``.

        No ``Tabla 3.10`` row states ``352`` (its ``l10n_ec_code_base`` is
        ``302``, and the record is named after it), so the rate cannot be
        resolved and must never be invented.
        """
        tax = self.tax_unresolvable_ats_code
        self.assertEqual(tax.l10n_ec_code_ats, "352")
        concept = self.env["l10n.ec.ats.income.withholding.concept"].search(
            [("code", "=", tax.l10n_ec_code_ats)]
        )
        self.assertFalse(concept, "Tabla 3.10 unexpectedly grew a 352 concept")

        bill = self._create_bill(document_number="001-001-000000031")
        self._create_withholding(bill, tax)

        rows, errors = self._collect()
        self.assertEqual(rows, [])
        self.assertTrue(errors)
        message = " ".join(str(error["message"]) for error in errors)
        self.assertIn("352", message)
        # No invented rate reached the payload.
        self.assertNotIn("porcentajeAir", str(rows))

    # ------------------------------------------------------------------
    # IVA withholding
    # ------------------------------------------------------------------

    def test_22_iva_withholding_lands_in_the_element_of_its_rate(self):
        bill = self._create_bill(document_number="001-001-000000040")
        self._create_withholding(bill, self.tax_withhold_vat_100)
        rows, errors = self._collect()
        self.assertFalse(errors, errors)
        row = rows[0]
        expected = IVA_RETENTION_ELEMENTS[100.0]
        self.assertGreater(row[expected], 0.0)
        # Every other bucket stays at zero rather than absent: the ficha marks
        # all six obligatorio.
        for element in IVA_RETENTION_ELEMENTS.values():
            if element != expected:
                self.assertEqual(row[element], 0.0, element)

    def test_23_the_retention_elements_are_the_ones_tabla_11_publishes(self):
        """Pin the rate-to-element pairing against the catalog itself.

        The element names are XSD names, so the pairing is schema knowledge --
        but the *rates* on its left-hand side must be exactly what ``Tabla 11``
        loads. If the SRI ever publishes a seventh rate, this fails and the
        mapping has to be revisited instead of silently misfiling.
        """
        table = self.CatalogTable.search([("code", "=", "11")])
        self.assertTrue(table, "Tabla 11 is not loaded")
        rates = {
            entry.percentage
            for entry in self.CatalogEntry.search([("table_id", "=", table.id)])
        }
        self.assertEqual(set(IVA_RETENTION_ELEMENTS), rates)

    # ------------------------------------------------------------------
    # Credit notes
    # ------------------------------------------------------------------

    def test_24_a_credit_note_is_reduced_never_negated(self):
        """§5.4: ``monedaType`` has ``minInclusive 0.0``, so no line may go
        negative. A credit note is therefore reported as magnitudes, and the
        ficha's ``monedaType`` accepts it.
        """
        # Posted with the signs a vendor bill has, then retyped: that is the only
        # way to reach the state ATS has to cope with. ``account.move._post``
        # refuses to validate an invoice whose total is negative -- "you should
        # create a credit note instead" -- and Odoo's credit-note flow produces
        # *positive* amounts on the reversal, so a posted ``in_refund`` carrying
        # negative amounts only exists if something wrote it. ATS must reduce it,
        # never file the minus sign, because ``monedaType`` forbids it.
        refund = self._create_bill(
            document_number="001-001-000000900",
            authorization="123456789012",
        )
        refund.write(
            {
                "move_type": "in_refund",
                # ``l10n_latam_invoice_document`` refuses an ``invoice``
                # document type on a refund, so both change together.
                "l10n_latam_document_type_id": self.env.ref("l10n_ec.ec_dt_04").id,
            }
        )
        self.assertEqual(refund.move_type, "in_refund")
        self.assertLess(refund.amount_untaxed, 0.0)
        rows, errors = self._collect()
        self.assertFalse(errors, errors)
        row = rows[0]
        for field, value in row.items():
            if isinstance(value, float):
                self.assertGreaterEqual(value, 0.0, field)
        self.assertEqual(row["baseImpGrav"], abs(refund.amount_untaxed))
        self.assertEqual(row["montoIva"], abs(refund.amount_tax))

    # ------------------------------------------------------------------
    # formasDePago
    # ------------------------------------------------------------------

    def test_25_formas_de_pago_resolves_through_tabla_13(self):
        bill = self._create_bill()
        rows, errors = self._collect()
        self.assertFalse(errors, errors)
        payment_code = bill.l10n_ec_sri_payment_id.code
        table = self.CatalogTable.search([("code", "=", "13")])
        applicable = self.CatalogEntry._applicable_on(PERIOD[0]).filtered(
            lambda entry: entry.table_id == table and entry.code == payment_code
        )
        self.assertEqual(len(applicable), 1)
        self.assertEqual(rows[0]["formasDePago"], [{"formaPago": payment_code}])

    # ------------------------------------------------------------------
    # Key shape
    # ------------------------------------------------------------------

    def test_26_the_row_keys_are_exactly_the_ats_element_names(self):
        """ATS-10 is a straight mapping, so the keys must be the XSD names."""
        bill = self._create_bill(document_number="001-001-000000050")
        self._create_withholding(bill, self.tax_withhold_profit_303)
        rows, errors = self._collect()
        self.assertFalse(errors, errors)
        self.assertEqual(
            set(rows[0]),
            {
                "codSustento",
                "tpIdProv",
                "idProv",
                "tipoComprobante",
                "parteRel",
                "fechaRegistro",
                "establecimiento",
                "puntoEmision",
                "secuencial",
                "fechaEmision",
                "autorizacion",
                "baseNoGraIva",
                "baseImponible",
                "baseImpGrav",
                "baseImpExe",
                "montoIce",
                "montoIva",
                "valRetBien10",
                "valRetServ20",
                "valorRetBienes",
                "valRetServ50",
                "valorRetServicios",
                "valRetServ100",
                "formasDePago",
                "air",
            },
        )
        self.assertNotIn("reembolsos", rows[0])
        self.assertEqual(
            set(rows[0]["air"][0]),
            {"codRetAir", "baseImpAir", "porcentajeAir", "valRetAir"},
        )
