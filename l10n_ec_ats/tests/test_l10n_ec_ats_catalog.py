import re
from datetime import date

from odoo import fields
from odoo.tests.common import TransactionCase

# --------------------------------------------------------------------------
# Expectations transcribed from the SRI catalog, one constant per rule.
#
# Every value below is a statement about ``Catalogo_ATS.xls``, sheet
# ``TABLAS REFERENCIALES``. The source cell is named next to each constant so
# a reviewer can check it without re-parsing the workbook.
# --------------------------------------------------------------------------

IN_SCOPE_TABLE_CODES = (
    "A",
    "01",
    "02",
    "04",
    "05",
    "11",
    "12",
    "13",
    "14",
    "15",
    "20",
    "21",
)

# Tables that serve only the ATS blocks excluded by the feature document.
# Nothing is loaded for them, so nothing may exist in the registry.
OUT_OF_SCOPE_TABLE_CODES = (
    "06",
    "07",
    "08",
    "09",
    "10",
    "16",
    "17",
    "18",
    "19",
    "3.10",
)

# The ``Código`` column as the SRI spells it, per table. Two digits is the
# norm; the exceptions are read straight off the sheet.
#
#   A   -- ``B8:B14``  single digit, and the SRI skips 3.
#   04  -- ``B49:B88`` three digits are real (294, 344, 364, 370..375).
#   11  -- ``B223:B228`` mixes 1..3 with 9..11.
#   20  -- ``C512:C513`` emission type, a letter: E / F.
#   12  -- no code column at all; the identity of the row is its percentage,
#          so the code is that percentage rendered as two digits.
CODE_FORMATS = {
    "A": r"[1245678]",
    "01": r"\d{2}",
    "02": r"\d{2}",
    "04": r"\d{1,3}",
    "05": r"\d{2}",
    "11": r"\d{1,2}",
    "12": r"\d{2}",
    "13": r"\d{2}",
    "14": r"\d{2}",
    "15": r"\d{2}",
    "20": r"[EF]",
    "21": r"\d{2}",
}

# ``Tabla 12`` identifies a regime by its percentage, because the sheet has no
# code column of its own. Its ``code`` is therefore the value itself, so
# contiguity is a property of the table, not of a code series: the SRI has no
# 12% regime in force between 31/05/2001 and 01/09/2001, nor between
# 31/05/2016 and 01/06/2017. See ``test_tabla12_rate_series_is_contiguous_as_a_whole``.
VALUE_KEYED_TABLES = frozenset({"12"})

# ``TABLA 11`` -- ``B222:C228``.
TABLA11_PERCENTAGES = {10.0, 20.0, 30.0, 50.0, 70.0, 100.0}
# ``TABLA 12`` -- ``B232:B236``. The source stores fractions (0.12, 0.14)
# while the ATS field is a whole percent, hence 12 and 14.
TABLA12_PERCENTAGES = {12.0, 14.0}

# Tables whose source carries no validity date at all. A, 01, 04, 14 and 15
# have no date column, or spell it ``vacío`` in every row. The mixin makes
# ``date_start`` required, so these rows carry a sentinel that is NOT a
# validity date: it marks the entry as undated in the source. ``date_end``
# stays empty so the entry reads as open-ended.
UNDATED_SENTINEL = "1900-01-01"
UNDATED_TABLE_CODES = frozenset({"A", "01", "04", "14", "15"})

# ``TABLA 4`` -> ``TABLA 5``: the pairs the SRI states on one side only.
# ``F88`` says document ``375`` (liquidación de compra RISE) is supported by
# sustentos 01..08, but none of ``D97``..``D104`` names 375 back. The
# workbook contradicts itself, so the gap is recorded rather than resolved.
# If a future SRI release closes it this set shrinks and the test fails.
TABLA5_RECIPROCAL_GAPS = frozenset(
    (sustento, "375") for sustento in ("01", "02", "03", "04", "05", "06", "07", "08")
)

# ``TABLA 2`` -> referencial A: codes whose ``Tipo Transacción`` cell names no
# referencial A row. ``C37:C39`` read FONDOS Y FIDEICOMISOS while referencial A
# ``B13`` reads "Fondos y Financiero" -- different names, and the catalog
# offers no other link. ``C40`` reads COMPROBANTES ANULADOS, which referencial
# A does not carry at all. Leaving the field empty is the honest reading; the
# generation preflight is what reports them.
TABLA2_UNMAPPED_CODES = frozenset({"15", "16", "17", "18"})

# ``Tabla 4`` columns D and F spell the literal ``ninguno`` on the rows that
# have no such list. Those become empty fields, not missing data.
#
#   column F -- rows 54, 55, 56, 61, 62, 66, 67, 68, 72, 76, 77, 78, 79,
#               83, 84, 85, 86, 87
#   column D -- rows 54, 55
TABLA4_NO_SUSTENTO_CODES = frozenset(
    {
        "6",
        "7",
        "8",
        "16",
        "18",
        "22",
        "23",
        "24",
        "44",
        "49",
        "50",
        "51",
        "52",
        "370",
        "371",
        "372",
        "373",
        "374",
    }
)
TABLA4_NO_SEQUENCE_CODES = frozenset({"6", "7"})


class TestL10nEcAtsCatalog(TransactionCase):
    """Integrity of the SRI referential catalogs loaded from ``data/``.

    Level 1 and Level 2 of the completeness control: the coverage manifest
    must match what was loaded, and the loaded data must satisfy the
    structural invariants the SRI catalog is supposed to hold.
    """

    # Helpers ------------------------------------------------------------

    def _table(self, code):
        """Return the registry record for ``code``, failing when absent."""
        table = self.env["l10n.ec.ats.catalog.table"].search([("code", "=", code)])
        self.assertEqual(len(table), 1, f"Expected exactly one catalog table {code!r}")
        return table

    def _entries(self, code):
        return self._entries_model().search([("table_id", "=", self._table(code).id)])

    def _entries_model(self):
        return self.env["l10n.ec.ats.catalog.entry"]

    def _codes(self, raw):
        """Split a comma-separated cross-reference cell into a code list."""
        return [token.strip() for token in (raw or "").split(",") if token.strip()]

    def _iso(self, value):
        return value and value.isoformat()

    # Coverage manifest (Level 1) ----------------------------------------

    def test_every_in_scope_table_is_registered(self):
        found = self.env["l10n.ec.ats.catalog.table"].search([]).mapped("code")
        self.assertEqual(sorted(found), sorted(IN_SCOPE_TABLE_CODES))

    def test_coverage_manifest_matches_loaded_entries(self):
        """The truncated-import detector.

        ``entry_count`` is the number of rows the spreadsheet has for the
        table. If a re-import or a hand edit loses a single entry the two
        numbers diverge, and generation would silently read a hole.
        """
        for code in IN_SCOPE_TABLE_CODES:
            table = self._table(code)
            self.assertGreater(
                table.entry_count,
                0,
                f"Table {code!r} declares an empty coverage manifest",
            )
            loaded = self._entries_model().search_count([("table_id", "=", table.id)])
            self.assertEqual(
                loaded,
                table.entry_count,
                f"Table {code!r} loaded {loaded} entries "
                f"but its manifest declares {table.entry_count}",
            )

    def test_tables_declare_their_source_and_in_scope_flag(self):
        for code in IN_SCOPE_TABLE_CODES:
            table = self._table(code)
            self.assertTrue(table.in_scope, f"Table {code!r} must be flagged in scope")
            self.assertTrue(table.load_order, f"Table {code!r} needs a load order")
            self.assertIn(
                "TABLAS REFERENCIALES",
                table.source_reference.upper(),
                f"Table {code!r} does not name the sheet it came from",
            )

    # Code format ---------------------------------------------------------

    def test_entry_codes_match_the_format_their_table_declares(self):
        for code, pattern in CODE_FORMATS.items():
            expression = re.compile(f"^({pattern})$")
            for entry in self._entries(code):
                self.assertRegex(
                    entry.code,
                    expression,
                    f"Table {code!r} entry {entry.code!r} does not match {pattern}",
                )

    def test_codes_are_unique_per_table_when_the_source_has_no_series(self):
        """Only ``TABLA 12`` repeats a code, because it is the one table whose
        row identity is a value that also changes over time."""
        for code in set(IN_SCOPE_TABLE_CODES) - {"12"}:
            codes = self._entries(code).mapped("code")
            self.assertEqual(
                len(codes),
                len(set(codes)),
                f"Table {code!r} has duplicate codes: {sorted(codes)}",
            )

    # Referential integrity ----------------------------------------------

    def test_tabla5_document_type_codes_all_exist_in_tabla4(self):
        documents = set(self._entries("04").mapped("code"))
        for entry in self._entries("05"):
            for document in self._codes(entry.document_type_codes):
                self.assertIn(
                    document,
                    documents,
                    f"Tabla 5 code {entry.code!r} references unknown "
                    f"Tabla 4 document {document!r}",
                )

    def test_tabla4_sustento_codes_all_exist_in_tabla5(self):
        sustentos = set(self._entries("05").mapped("code"))
        for entry in self._entries("04"):
            for sustento in self._codes(entry.document_type_codes):
                self.assertIn(
                    sustento,
                    sustentos,
                    f"Tabla 4 document {entry.code!r} references unknown "
                    f"Tabla 5 support {sustento!r}",
                )

    def test_tabla4_tabla5_reciprocity_gaps_are_exactly_the_source_ones(self):
        """``TABLA 4`` column F names the sustentos supporting each document and
        ``TABLA 5`` column D names the documents each sustento supports. The SRI
        states the two independently and they do not fully agree, so every pair
        must be reciprocated except the documented ones. Asserting the exact
        set means a newly invented or newly dropped link fails the test.
        """
        by_sustento = {
            entry.code: self._codes(entry.document_type_codes)
            for entry in self._entries("05")
        }
        gaps = set()
        for document in self._entries("04"):
            for sustento in self._codes(document.document_type_codes):
                if (
                    sustento in by_sustento
                    and document.code not in by_sustento[sustento]
                ):
                    gaps.add((sustento, document.code))
        self.assertEqual(gaps, set(TABLA5_RECIPROCAL_GAPS))

    def test_tabla4_sequences_use_the_two_digit_form(self):
        for entry in self._entries("04"):
            for code in self._codes(entry.sequence_type_codes):
                self.assertRegex(code, r"^\d{2}$")

    def test_tabla2_transaction_type_codes_all_exist_in_referencial_a(self):
        types = set(self._entries("A").mapped("code"))
        for entry in self._entries("02"):
            for code in self._codes(entry.transaction_type_codes):
                self.assertIn(
                    code,
                    types,
                    f"Tabla 2 code {entry.code!r} references unknown "
                    f"transaction type {code!r}",
                )

    def test_tabla2_unmapped_codes_are_exactly_the_source_gaps(self):
        unmapped = {
            entry.code
            for entry in self._entries("02")
            if not self._codes(entry.transaction_type_codes)
        }
        self.assertEqual(unmapped, set(TABLA2_UNMAPPED_CODES))

    def test_only_the_tables_that_carry_cross_references_do(self):
        """Keeps a stray cross-reference on a table that has none in the
        spreadsheet from passing unnoticed."""
        carriers = {
            ("02", "transaction_type_codes"),
            ("04", "document_type_codes"),
            ("04", "sequence_type_codes"),
            ("05", "document_type_codes"),
        }
        spelled_none = {
            ("04", "document_type_codes"): TABLA4_NO_SUSTENTO_CODES,
            ("04", "sequence_type_codes"): TABLA4_NO_SEQUENCE_CODES,
        }
        for code in IN_SCOPE_TABLE_CODES:
            for field_name in (
                "transaction_type_codes",
                "document_type_codes",
                "sequence_type_codes",
            ):
                for entry in self._entries(code):
                    expected = (code, field_name) in carriers
                    if (code, field_name) in spelled_none:
                        expected = (
                            expected
                            and entry.code not in spelled_none[(code, field_name)]
                        )
                    unmapped = (
                        code == "02"
                        and entry.code in TABLA2_UNMAPPED_CODES
                        and field_name == "transaction_type_codes"
                    )
                    expected = expected and not unmapped
                    self.assertEqual(
                        bool(entry[field_name]),
                        expected,
                        "Table {!r} code {!r}: {} should {}be populated".format(
                            code, entry.code, field_name, "" if expected else "not "
                        ),
                    )

    # Structural invariants (Level 2) ------------------------------------

    def test_windows_are_disjoint_per_table_and_code(self):
        for code in IN_SCOPE_TABLE_CODES:
            entries = self._entries(code)
            for entry in entries:
                siblings = entries.filtered(
                    lambda other, entry=entry: (
                        other.code == entry.code and other.id != entry.id
                    )
                )
                for sibling in siblings:
                    self.assertFalse(
                        entry._temporal_overlapping(sibling),
                        f"Table {code!r} code {entry.code!r} has overlapping "
                        f"windows {entry.date_start}..{entry.date_end} and "
                        f"{sibling.date_start}..{sibling.date_end}",
                    )

    def test_no_internal_gaps_per_table(self):
        """Level 2 contiguity: inside a table, the union of the windows is
        contiguous. A hole means a period the SRI covered and the catalog does
        not, which is the failure the invariant exists to catch."""
        for code in IN_SCOPE_TABLE_CODES:
            gaps = self._entries_model()._temporal_gaps(
                [("table_id", "=", self._table(code).id)]
            )
            self.assertEqual(
                gaps,
                [],
                f"Table {code!r} has uncovered windows: {gaps}",
            )

    def test_no_internal_gaps_within_a_code_series(self):
        """Contiguity per ``(table, code)``, for every table whose code names a
        stable thing whose value may change -- a rate, a form of payment.

        ``Tabla 12`` is excluded on purpose. Its code *is* the percentage,
        because the sheet has no code column at all, so a rate change reads as
        a hole in the series of the rate it left: the SRI genuinely has no 12%
        regime in force between 31/05/2001 and 01/09/2001, nor between
        31/05/2016 and 01/06/2017. Those are 14% regimes, in the ``14`` series,
        and the table-level check above is what proves the table has no hole.
        """
        for code in set(IN_SCOPE_TABLE_CODES) - VALUE_KEYED_TABLES:
            entries = self._entries(code)
            for entry_code in set(entries.mapped("code")):
                if len(entries.filtered(lambda e, c=entry_code: e.code == c)) < 2:
                    continue
                gaps = self._entries_model()._temporal_gaps(
                    [("table_id", "=", self._table(code).id), ("code", "=", entry_code)]
                )
                self.assertEqual(
                    gaps,
                    [],
                    f"Table {code!r} code {entry_code!r} has uncovered windows: {gaps}",
                )

    def test_tabla12_rate_series_is_contiguous_as_a_whole(self):
        """``C232:D236`` -- the five regimes tile 01/01/2000 onwards with no
        hole and no overlap, so ``_applicable_on`` never returns nothing and
        never returns two."""
        table = self._table("12")
        for probe in (
            "2000-01-01",
            "2001-05-31",
            "2001-06-01",
            "2001-08-31",
            "2001-09-01",
            "2016-05-31",
            "2016-06-01",
            "2017-05-31",
            "2017-06-01",
            "2026-10-02",
        ):
            applicable = (
                self._entries("12")
                ._applicable_on(probe)
                .filtered(lambda entry, table=table: entry.table_id == table)
            )
            self.assertEqual(
                len(applicable),
                1,
                f"Tabla 12 has {len(applicable)} rates in force on {probe}",
            )
        self.assertEqual(
            self._rate_on("12", "2016-12-01"),
            14.0,
        )
        self.assertEqual(
            self._rate_on("12", "2017-06-01"),
            12.0,
        )
        self.assertEqual(table.entry_count, 5)

    def _rate_on(self, code, day):
        table = self._table(code)
        applicable = (
            self._entries(code)
            ._applicable_on(day)
            .filtered(lambda entry, table=table: entry.table_id == table)
        )
        self.assertEqual(len(applicable), 1)
        return applicable.percentage

    def test_undated_tables_use_the_documented_sentinel(self):
        for code in IN_SCOPE_TABLE_CODES:
            for entry in self._entries(code):
                if code in UNDATED_TABLE_CODES:
                    self.assertEqual(
                        self._iso(entry.date_start),
                        UNDATED_SENTINEL,
                        f"Table {code!r} code {entry.code!r} must carry the "
                        f"documented sentinel",
                    )
                    self.assertFalse(
                        entry.date_end,
                        f"Table {code!r} is undated in the source: "
                        f"date_end must stay open",
                    )
                else:
                    self.assertNotEqual(
                        self._iso(entry.date_start),
                        UNDATED_SENTINEL,
                        f"Table {code!r} carries real dates and must not use "
                        f"the sentinel",
                    )

    def test_dated_tables_end_where_the_successor_starts(self):
        """``TABLA 12`` code ``12`` is the only series with more than one
        window; ``C232:D236`` spells them out day by day."""
        series = self._entries("12").filtered(lambda entry: entry.code == "12")
        self.assertEqual(len(series), 3)
        windows = sorted((entry.date_start, entry.date_end) for entry in series)
        self.assertEqual(
            windows,
            [
                (fields.Date.to_date("2000-01-01"), fields.Date.to_date("2001-05-31")),
                (fields.Date.to_date("2001-09-01"), fields.Date.to_date("2016-05-31")),
                (fields.Date.to_date("2017-06-01"), False),
            ],
        )

    # Rate sanity ---------------------------------------------------------

    def test_tabla11_percentages_are_the_sri_set(self):
        for entry in self._entries("11"):
            self.assertIn(
                entry.percentage,
                TABLA11_PERCENTAGES,
                f"Tabla 11 code {entry.code!r} has percentage {entry.percentage!r}",
            )

    def test_tabla12_percentages_are_twelve_or_fourteen(self):
        for entry in self._entries("12"):
            self.assertIn(
                entry.percentage,
                TABLA12_PERCENTAGES,
                f"Tabla 12 percentage {entry.percentage!r} is neither 12 nor 14",
            )

    def test_no_table_outside_11_and_12_carries_a_percentage(self):
        for code in set(IN_SCOPE_TABLE_CODES) - {"11", "12"}:
            for entry in self._entries(code):
                self.assertFalse(
                    entry.percentage,
                    f"Table {code!r} code {entry.code!r} must not carry a percentage",
                )

    # Spot assertions, each naming its source cell -----------------------

    def test_tabla12_has_five_regimes_and_the_current_one_starts_2017_06_01(self):
        """``B232:D236`` -- five rows, the last being 12% from 01/06/2017."""
        entries = self._entries("12")
        self.assertEqual(len(entries), 5)
        current = entries.filtered(lambda entry: not entry.date_end)
        self.assertEqual(len(current), 1)
        self.assertEqual(current.percentage, 12.0)
        self.assertEqual(current.code, "12")
        self.assertEqual(self._iso(current.date_start), "2017-06-01")

    def test_tabla13_code_07_expires_on_2016_08_31(self):
        """``B247:E247`` -- TRANSFERENCIA PROPIO BANCO."""
        entry = self._entries("13").filtered(lambda entry: entry.code == "07")
        self.assertEqual(len(entry), 1)
        self.assertEqual(entry.description, "TRANSFERENCIA PROPIO BANCO")
        self.assertEqual(self._iso(entry.date_start), "2013-01-01")
        self.assertEqual(self._iso(entry.date_end), "2016-08-31")

    def test_tabla5_code_15_starts_on_2020_06_01(self):
        """``E111`` holds the Excel serial 43983."""
        entry = self._entries("05").filtered(lambda entry: entry.code == "15")
        self.assertEqual(len(entry), 1)
        self.assertEqual(self._iso(entry.date_start), "2020-06-01")
        self.assertFalse(entry.date_end)
        self.assertEqual(
            self._codes(entry.document_type_codes),
            ["1", "2", "3", "4", "5", "12", "15"],
        )

    def test_tabla11_code_1_is_thirty_percent(self):
        """``B225:C225`` -- code 1 at 30%, from the serial 37257."""
        entry = self._entries("11").filtered(lambda entry: entry.code == "1")
        self.assertEqual(len(entry), 1)
        self.assertEqual(entry.percentage, 30.0)
        self.assertEqual(self._iso(entry.date_start), "2002-01-01")

    def test_tabla2_code_09_expires_the_day_before_code_20_starts(self):
        """``F31`` holds the serial 42063 and ``E42`` the serial 42064."""
        expired = self._entries("02").filtered(lambda entry: entry.code == "09")
        successor = self._entries("02").filtered(lambda entry: entry.code == "20")
        self.assertEqual(self._iso(expired.date_end), "2015-02-28")
        self.assertEqual(self._iso(successor.date_start), "2015-03-01")

    def test_referencial_a_matches_the_transaction_types_ats_tipo_1_uses(self):
        """``B8:C14`` -- seven rows, and the SRI skips code 3."""
        entries = self._entries("A")
        self.assertEqual(len(entries), 7)
        self.assertNotIn("3", entries.mapped("code"))
        self.assertEqual(
            dict(
                zip(entries.mapped("code"), entries.mapped("description"), strict=False)
            ),
            {
                "1": "Compra",
                "2": "Venta",
                "4": "Exportación",
                "5": "Tarjetas de Crédito",
                "6": "Rendimientos Financieros",
                "7": "Fondos y Financiero",
                "8": "Otros ingresos del exterior",
            },
        )

    # The out-of-scope tables are absent ---------------------------------

    def test_out_of_scope_tables_are_not_registered(self):
        registry = self.env["l10n.ec.ats.catalog.table"]
        for code in OUT_OF_SCOPE_TABLE_CODES:
            self.assertFalse(
                registry.search_count([("code", "=", code)]),
                f"Table {code!r} serves only an out-of-scope block and must "
                f"not be loaded",
            )

    def test_no_entry_points_at_an_unregistered_table(self):
        tables = self.env["l10n.ec.ats.catalog.table"]
        self.assertEqual(
            set(tables.search([]).mapped("code")) - set(IN_SCOPE_TABLE_CODES), set()
        )
        for entry in self._entries_model().search([]):
            self.assertIn(entry.table_id.code, IN_SCOPE_TABLE_CODES)

    # Triangulation: prove the detectors fire.
    #
    # An integrity suite that only ever inspects healthy data proves nothing
    # about whether it would notice an unhealthy one. Each test below breaks
    # one invariant on purpose, inside the rolled-back transaction, and
    # asserts the matching check reports it.

    def test_the_coverage_manifest_detects_a_lost_entry(self):
        table = self._table("13")
        before = self._entries_model().search_count([("table_id", "=", table.id)])
        self._entries("13")[:1].unlink()
        after = self._entries_model().search_count([("table_id", "=", table.id)])
        self.assertNotEqual(after, table.entry_count)
        self.assertEqual(after, before - 1)

    def test_overlap_detection_detects_a_duplicated_window(self):
        original = self._entries("12").filtered(lambda entry: entry.code == "14")[:1]
        clone = original.copy({"date_end": False})
        self.assertTrue(original._temporal_overlapping(clone))
        self.assertTrue(clone._temporal_overlapping(original))

    def test_gap_detection_detects_a_hole_in_a_series(self):
        table = self._table("13")
        original = self._entries("13").filtered(lambda entry: entry.code == "07")[:1]
        original.copy({"date_start": "2016-10-01", "date_end": False})
        gaps = self._entries_model()._temporal_gaps(
            [("table_id", "=", table.id), ("code", "=", "07")]
        )
        self.assertEqual(gaps, [(date(2016, 9, 1), date(2016, 9, 30))])

    def test_referential_integrity_detects_a_dangling_document(self):
        entry = self._entries("05")[:1]
        entry.write({"document_type_codes": "999"})
        documents = set(self._entries("04").mapped("code"))
        self.assertNotIn("999", documents)

    def test_referential_integrity_detects_an_unreciprocated_link(self):
        # Tabla 5 code ``10`` supports document ``19`` only, so claiming it
        # also supports document ``1`` makes the link one-sided.
        entry = self._entries("04").filtered(lambda candidate: candidate.code == "1")[
            :1
        ]
        entry.write({"document_type_codes": f"{entry.document_type_codes}, 10"})
        by_sustento = {
            candidate.code: self._codes(candidate.document_type_codes)
            for candidate in self._entries("05")
        }
        gaps = {
            (sustento, document.code)
            for document in self._entries("04")
            for sustento in self._codes(document.document_type_codes)
            if sustento in by_sustento and document.code not in by_sustento[sustento]
        }
        self.assertNotEqual(gaps, set(TABLA5_RECIPROCAL_GAPS))

    def test_rate_sanity_detects_an_impossible_rate(self):
        entry = self._entries("11")[:1]
        entry.write({"percentage": 42.0})
        self.assertNotIn(entry.percentage, TABLA11_PERCENTAGES)

    def test_the_sentinel_is_distinguishable_from_a_real_date(self):
        """A sentinel that looks like real data is worse than no sentinel: it
        would be read as a business fact. Every real window in the loaded
        catalog starts inside the SRI's own range of published dates."""
        for code in IN_SCOPE_TABLE_CODES:
            for entry in self._entries(code):
                if code in UNDATED_TABLE_CODES:
                    continue
                self.assertGreater(entry.date_start, date(1999, 12, 31))
