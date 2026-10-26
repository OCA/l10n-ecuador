import re
from datetime import date

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase

# --------------------------------------------------------------------------
# Expectations transcribed from the SRI catalog, one constant per rule.
#
# Every value below is a statement about ``Catalogo_ATS.xls``, sheet
# ``TABLAS RETENCIONES``. The source cell is named next to each constant so a
# reviewer can check it without re-parsing the workbook.
# --------------------------------------------------------------------------

CONCEPT_MODEL = "l10n.ec.ats.income.withholding.concept"
RATE_MODEL = "l10n.ec.ats.income.withholding.rate"

# ``ats.xsd`` lines 238-246, ``codRetAirType``: ``minLength 3``,
# ``maxLength 5``, ``pattern [A-Za-z0-9]*``. Alphanumeric suffixes such as
# ``303A``, ``323B1`` and ``323E2`` are real codes, never numbers to parse.
COD_RET_AIR = re.compile(r"^[A-Za-z0-9]{3,5}$")

# Distinct values of the ``Número de campo`` column across the 22 date-era
# blocks of ``TABLAS RETENCIONES`` (rows 5 to 291, columns B..DC). Counted by
# reading every code cell, not inferred from the plan.
CONCEPT_COUNT = 414

# ``C37``..``C40`` (and the same four cells in 18 blocks) read ``323 M`` ..
# ``323 P`` with a space, which ``codRetAirType``'s ``[A-Za-z0-9]*`` rejects.
# The sheet's own sibling codes -- ``323A``, ``323B1``, ``323C``..``323K``,
# ``323E``, ``323E2`` -- carry the same suffix with no space, so the stored
# code drops it. Nothing else about the code is touched.
SPACED_CODES_IN_SOURCE = frozenset({"323 M", "323 N", "323 O", "323 P"})
NORMALISED_CODES = ("323M", "323N", "323O", "323P")

# The newest era, ``B2`` = ``DESDE 06/AGOSTO/2026``. Open-ended: the sheet
# states no ``HASTA`` for it, and it is the only block that does not.
NEWEST_ERA = date(2026, 8, 6)

# ``E16`` -- prose, not a number. The plan's trap: reading it as ``1`` would
# invent a rate the SRI never stated.
CELL_310_PROSE = "1 /0 según resolución NAC-DGERCGC26-00000028"
# ``E20`` -- the fractional percentage that makes the field a Float.
CELL_312C = 1.75

# Spot values, one per era, each naming the cell it was read from. The newest
# era states no ``HASTA`` and is the only open-ended one, so its ``date_end``
# is ``False``.
SPOT_VALUES = (
    # code, era start, source cell, expected percentage, era end
    ("303", date(2026, 8, 6), "E5", 10.0, False),
    ("303", date(2009, 1, 1), "DC5", 8.0, date(2010, 5, 31)),
    ("322", date(2015, 3, 1), "CG25", 1.0, date(2016, 4, 30)),
    ("322", date(2010, 6, 1), "CY14", 1.0, date(2011, 12, 31)),
    ("343B", date(2026, 8, 6), "E75", 2.0, False),
    ("312", date(2026, 8, 6), "E18", 2.0, False),
    ("323E2", date(2026, 8, 6), "E32", 0.0, False),
    ("504J", date(2026, 8, 6), "E103", 25.0, False),
)

# One description per era, each naming the cell it was read from. Codes that
# the SRI reworded between eras are deliberate: a leak of one era's wording
# onto another's row is what this catches.
SPOT_DESCRIPTIONS = (
    ("303", date(2009, 1, 1), "DB5", "Honorarios profesionales y dietas"),
    (
        "322",
        date(2012, 1, 1),
        "CT14",
        "Seguros y reaseguros (primas y cesiones)",
    ),
    (
        "310",
        date(2014, 10, 1),
        "CK15",
        "Servicio de transporte privado de pasajeros o transporte público o "
        "privado de carga",
    ),
    (
        "312",
        date(2015, 3, 1),
        "CF17",
        "Transferencia de bienes muebles de naturaleza corporal",
    ),
    (
        "308",
        date(2020, 9, 1),
        "BB13",
        "Utilización o aprovechamiento de la imagen o renombre",
    ),
    (
        "303A",
        date(2024, 7, 1),
        "AC6",
        "Servicios profesionales prestados por sociedades residentes",
    ),
)

# Cells whose text is not a bare number: prose the catalog keeps verbatim in
# ``source_note`` rather than resolving into a percentage.
SPOT_PROSE = (
    # code, era start, source cell, expected source_note
    ("310", date(2026, 8, 6), "E16", CELL_310_PROSE),
    ("520G", date(2026, 8, 6), "E128", "0, 25, 37"),
    ("401AA", date(2012, 1, 1), "CU47", "-"),
)

# Cells that read as a number but cannot be one: three values strictly
# between 0 and 1, which is how this workbook writes a fraction. ``504G``
# reads ``0.25`` in 2015 and 2016 (CB91, CG89) and ``25`` from 2018 on;
# ``504F`` reads ``0.13`` in the same two eras (CB90, CG88); ``322`` reads
# ``0.0175`` in four (AS25, AX25, BC26, BH26) and ``1`` or ``2`` in the rest.
#
# Storing 0.25 as a percentage would state a quarter of a percent for a
# concept whose real rate is a quarter of a *hundred*, and the error would be
# invisible: 0.25 is a perfectly plausible-looking number. ``ats.xsd`` rules
# ``0.0175`` out independently, ``porcentajeAirType`` allowing two fraction
# digits, so it could not be emitted whatever it meant.
FRACTION_LIKE_CELLS = (
    ("322", date(2024, 1, 1), "AS25", "0.0175"),
    ("322", date(2022, 1, 1), "AX25", "0.0175"),
    ("322", date(2020, 9, 1), "BC26", "0.0175"),
    ("322", date(2020, 4, 1), "BH26", "0.0175"),
    ("504F", date(2016, 5, 1), "CB90", "0.13"),
    ("504F", date(2015, 3, 1), "CG88", "0.13"),
    ("504G", date(2016, 5, 1), "CB91", "0.25"),
    ("504G", date(2015, 3, 1), "CG89", "0.25"),
)

# ``source_note`` for a fraction-like cell is the verbatim cell, then the
# reading a maintainer would arrive at, then whether the same code's other
# eras corroborate it. The markers are deliberately unmissable: the failure
# this exists to prevent is a guessed rate filed as though the SRI published
# it, so nothing in the note may read as loaded data.
NOTE_SEPARATOR = " | "
NOT_DATA_MARKER = "NOT DATA"
PROPOSAL_MARKER = "PROPOSAL ONLY"
CORROBORATED_MARKER = "corroborated by"
UNCORROBORATED_MARKER = "NOT corroborated"


# Concepts the SRI itself drops from an era and reintroduces later, so their
# series has a hole the catalog must keep rather than paper over. Verified
# against the sheet one code column at a time: ``343`` is absent from the
# ``BZ``, ``CE`` and ``CJ`` columns, ``308`` from ``CJ`` alone, and so on.
#
# Filling one of these would mean inventing a rate for a period the SRI never
# published, so the hole is pinned instead: a re-import that invents a window
# fails here, and so does one that loses a rate and widens the hole.
SOURCE_ERA_HOLES = {
    "303A": [(date(2015, 3, 1), date(2024, 2, 29))],
    "308": [(date(2014, 10, 1), date(2015, 2, 28))],
    "333": [(date(2014, 10, 1), date(2015, 2, 28))],
    "336": [(date(2014, 10, 1), date(2015, 2, 28))],
    "337": [(date(2014, 10, 1), date(2015, 2, 28))],
    "340": [(date(2014, 10, 1), date(2015, 2, 28))],
    "342": [(date(2014, 10, 1), date(2015, 2, 28))],
    "343": [(date(2014, 10, 1), date(2018, 2, 28))],
    "344": [(date(2014, 10, 1), date(2015, 2, 28))],
    "345": [(date(2015, 3, 1), date(2018, 2, 28))],
    "346": [(date(2014, 10, 1), date(2018, 2, 28))],
    "347": [(date(2015, 3, 1), date(2016, 4, 30))],
    "348": [
        (date(2015, 3, 1), date(2016, 4, 30)),
        (date(2018, 3, 1), date(2019, 12, 31)),
    ],
    "349": [(date(2015, 3, 1), date(2016, 4, 30))],
    "504E": [(date(2016, 5, 1), date(2018, 2, 28))],
}


class TestL10nEcAtsIncomeWithholding(TransactionCase):
    """Integrity of ``Tabla 3.10``, the income withholding concepts.

    The concept is timeless; only the rate is dated. That asymmetry is the
    whole point, so the suite checks both halves: every concept obeys the
    ``codRetAir`` lexical shape, and every rate lands in a window that no
    other rate of the same concept claims.
    """

    # Helpers ------------------------------------------------------------

    def _concept(self, code):
        """Return the concept for ``code``, failing when absent."""
        concept = self.env[CONCEPT_MODEL].search([("code", "=", code)])
        self.assertEqual(len(concept), 1, f"Expected exactly one concept {code!r}")
        return concept

    def _rate(self, code, era_start):
        """Return the one rate ``code`` carries from ``era_start``."""
        concept = self._concept(code)
        rates = self.env[RATE_MODEL].search(
            [("concept_id", "=", concept.id), ("date_start", "=", era_start)]
        )
        self.assertEqual(
            len(rates),
            1,
            f"Concept {code!r} must carry exactly one rate from {era_start}, "
            f"found {len(rates)}",
        )
        return rates

    def _rates_of(self, code):
        concept = self._concept(code)
        return self.env[RATE_MODEL].search([("concept_id", "=", concept.id)])

    def _applicable_on(self, code, day):
        """Return the rate of ``code`` in force on ``day``.

        ``_applicable_on`` is a model-level helper: its ``search`` covers the
        whole model, not just the recordset it was called on, which is why the
        result is narrowed to the one concept. That narrowing is the caller's
        job in every real use too -- the generation preflight resolves a
        catalog entry and has to assert the answer holds exactly one record.
        """
        concept = self._concept(code)
        applicable = self.env[RATE_MODEL]._applicable_on(day)
        return applicable.filtered(lambda rate: rate.concept_id == concept)

    def _stored_percentage(self, rate):
        """Read the raw ``percentage`` column of ``rate``.

        ``fields.Float`` reads a NULL column back as ``0.0``
        (``Float.convert_to_record`` returns ``value or 0.0``), so a rate that
        keeps no percentage is indistinguishable from a rate of ``0`` through
        the ORM. Only the database tells them apart, and the difference is
        the point: ``323E2`` is a parsed ``0``, concept ``310`` is no value at
        all.
        """
        self.env.cr.execute(
            f"SELECT percentage FROM {self.env[RATE_MODEL]._table} WHERE id = %s",
            (rate.id,),
        )
        return self.env.cr.fetchone()[0]

    # Code format ---------------------------------------------------------

    def test_concept_codes_match_the_cod_ret_air_pattern(self):
        """``codRetAirType``: 3 to 5 characters, ``[A-Za-z0-9]*``.

        A code outside that shape could never be emitted in a valid ATS, so
        this is the one lexical invariant that has to hold for all of them.
        """
        for concept in self.env[CONCEPT_MODEL].search([]):
            self.assertRegex(
                concept.code,
                COD_RET_AIR,
                f"Concept code {concept.code!r} does not match "
                f"codRetAirType ([A-Za-z0-9]{{3,5}})",
            )

    def test_codes_with_a_space_in_the_source_are_the_four_suffix_series(self):
        """``C37``..``C40`` are the only four codes the sheet spells with a
        space. Pinning the set means a fifth such typo, or a silently
        rewritten one, fails instead of passing unnoticed."""
        for code in NORMALISED_CODES:
            concept = self._concept(code)
            self.assertNotIn(" ", concept.code)
        stored = set(self.env[CONCEPT_MODEL].search([]).mapped("code"))
        self.assertTrue(SPACED_CODES_IN_SOURCE.isdisjoint(stored))

    # Concept count -------------------------------------------------------

    def test_concept_count_matches_the_codes_the_sheet_states(self):
        """The truncated-import detector for ``Tabla 3.10``.

        ``CONCEPT_COUNT`` is the number of distinct values read from the
        ``Número de campo`` columns of all 22 era blocks. Losing one, or
        loading one twice, diverges here.
        """
        self.assertEqual(self.env[CONCEPT_MODEL].search_count([]), CONCEPT_COUNT)

    # Rate uniqueness -----------------------------------------------------

    def test_no_two_rates_of_one_concept_overlap(self):
        """Exactly one rate per ``(concept, era window)``.

        Two windows claiming the same day would make ``_applicable_on``
        return two records for a period, which is a coverage defect the
        generation preflight refuses. Asserting pairwise disjointness per
        concept is what proves the era blocks were imported as distinct
        windows rather than as one open-ended series.
        """
        rates = self.env[RATE_MODEL].search([])
        by_concept = {}
        for rate in rates:
            by_concept.setdefault(rate.concept_id, self.env[RATE_MODEL])
            by_concept[rate.concept_id] |= rate
        self.assertEqual(len(by_concept), CONCEPT_COUNT)
        for concept, concept_rates in by_concept.items():
            for rate in concept_rates:
                for other in concept_rates - rate:
                    self.assertFalse(
                        rate._temporal_overlapping(other),
                        f"Concept {concept.code!r} has overlapping rates "
                        f"{rate.date_start}..{rate.date_end} and "
                        f"{other.date_start}..{other.date_end}",
                    )

    # Contiguity ----------------------------------------------------------

    def test_no_concept_has_an_internal_gap_beyond_the_source_ones(self):
        """Inside a concept's series the windows tile without a hole.

        A concept that did not exist before its first appearance is not a
        hole -- that is the mixin's documented behaviour, since the span
        checked runs from the earliest ``date_start``. What must never happen
        is a period between two windows the SRI covered and this catalog does
        not.

        Fifteen concepts *do* have such a hole: the SRI drops them from one
        era and brings them back in a later one (``343`` is absent from the
        whole 2014-10-01..2018-02-28 run). Those are pinned rather than
        filled, because filling one would mean publishing a rate for a period
        the SRI never stated. Asserting the exact set means a re-import that
        invents a window fails, and so does one that loses a rate and leaves
        the hole wider than the sheet does.
        """
        rate_model = self.env[RATE_MODEL]
        found = {}
        for concept in self.env[CONCEPT_MODEL].search([]):
            gaps = rate_model._temporal_gaps([("concept_id", "=", concept.id)])
            if gaps:
                found[concept.code] = gaps
        self.assertEqual(found, SOURCE_ERA_HOLES)

    def test_the_pinned_holes_are_holes_the_sheet_leaves(self):
        """The other half of the pin: a hole the sheet does not have is
        still a hole, so the other 399 concepts must be contiguous."""
        rate_model = self.env[RATE_MODEL]
        for concept in self.env[CONCEPT_MODEL].search([]):
            if concept.code in SOURCE_ERA_HOLES:
                continue
            self.assertEqual(
                rate_model._temporal_gaps([("concept_id", "=", concept.id)]),
                [],
                f"Concept {concept.code!r} is not one of the source's own "
                f"holes and must be contiguous",
            )

    # Open-ended tail -----------------------------------------------------

    def test_the_newest_era_is_open_ended(self):
        """``B2`` = ``DESDE 06/AGOSTO/2026``, the only block with no ``HASTA``.

        A rate in the newest era that carried an end date would leave the
        catalog with no entry in force for the period being filed today.
        """
        newest = self.env[RATE_MODEL].search([("date_start", "=", NEWEST_ERA)])
        self.assertTrue(newest, "No rate starts in the newest era")
        self.assertEqual(
            newest.filtered("date_end"),
            self.env[RATE_MODEL],
            "Rates of the newest era must stay open-ended",
        )

    def test_at_least_one_concept_is_in_force_on_the_newest_era(self):
        in_force = self.env[RATE_MODEL]._applicable_on(NEWEST_ERA)
        self.assertTrue(in_force, "No rate is in force on the newest era")
        self.assertEqual(len(in_force), len(in_force.concept_id))

    # The prose cell ------------------------------------------------------

    def test_concept_310_prose_cell_is_unresolved_and_never_one(self):
        """``E16`` reads ``1 /0 según resolución NAC-DGERCGC26-00000028``.

        The cell names two candidate rates and a resolution, so the catalog
        states no single percentage. Importing it as ``1`` would be an
        assumed value dressed as data: the rate would look plausible and be
        silently wrong. ``unresolved`` with the verbatim text is the honest
        reading, and it makes the generation preflight refuse the period
        instead of filing a guess.
        """
        rate = self._rate("310", NEWEST_ERA)
        self.assertTrue(rate.unresolved)
        self.assertIsNone(
            self._stored_percentage(rate),
            "An unresolved rate must keep percentage NULL, not 0",
        )
        self.assertEqual(rate.percentage, 0.0)
        self.assertNotEqual(rate.percentage, 1)
        self.assertEqual(rate.source_note, CELL_310_PROSE)
        self.assertIn("NAC-DGERCGC26-00000028", rate.source_note)

    def test_the_other_prose_cell_of_the_newest_era_is_also_unresolved(self):
        """``E61`` reads ``0 /1 según resolución NAC-DGERCGC26-00000028``.

        The same trap on a different concept: proving the handling is a rule
        about the cell, not a special case written for ``310``.
        """
        rate = self._rate("332E", NEWEST_ERA)
        self.assertTrue(rate.unresolved)
        self.assertIsNone(self._stored_percentage(rate))
        self.assertEqual(
            rate.source_note, "0 /1 según resolución NAC-DGERCGC26-00000028"
        )

    def test_a_prose_cell_keeps_no_note_when_it_was_a_number(self):
        """``source_note`` exists for the unresolvable cell only.

        A number needs no note, and a note on a resolved rate would suggest
        there is something left to interpret.
        """
        for code, era_start, _cell, percentage, _end in SPOT_VALUES:
            rate = self._rate(code, era_start)
            self.assertFalse(rate.unresolved, f"{code!r}@{era_start}")
            self.assertEqual(rate.percentage, percentage)
            self.assertFalse(rate.source_note, f"{code!r}@{era_start}")

    # The fractional cell -------------------------------------------------

    def test_concept_312c_carries_one_point_seven_five(self):
        """``E20`` reads ``1.75``.

        A fractional percentage is why ``percentage`` is a ``Float``: an
        ``Integer`` field would round 1.75 to 2 and quietly misstate the
        rate, and 1.75 is a real published value for ``312C``.
        """
        rate = self._rate("312C", NEWEST_ERA)
        self.assertEqual(rate.percentage, CELL_312C)
        self.assertFalse(rate.unresolved)

    def test_the_exempt_zero_is_a_parsed_rate_not_a_missing_one(self):
        """``E32`` reads ``0`` for ``323E2``.

        ``0`` is a real answer -- the concept is exempt -- so it must be a
        resolved rate holding zero, never an unresolved one. This is the case
        that makes ``unresolved`` a flag rather than a proxy for "the number
        is falsy".
        """
        rate = self._rate("323E2", NEWEST_ERA)
        self.assertFalse(rate.unresolved)
        self.assertEqual(rate.percentage, 0.0)
        self.assertIsNotNone(
            self._stored_percentage(rate),
            "A parsed 0 must be stored, not left NULL",
        )

    # Spot values ---------------------------------------------------------

    def test_fraction_like_cells_are_never_read_as_percentages(self):
        """The eight cells that look numeric and are not percentages.

        ``0.25`` for ``504G`` would read as a quarter of one percent for a
        concept the SRI withholds at 25. The value is plausible enough to
        survive review, which is exactly why it is pinned: reading it as a
        percentage is silent, and reading it as 25 would be inventing. The
        only honest answer is the cell text plus ``unresolved``.
        """
        found = {}
        for code, era_start, cell, note in FRACTION_LIKE_CELLS:
            rate = self._rate(code, era_start)
            self.assertTrue(
                rate.unresolved, f"{code!r}@{era_start} ({cell}) must be unresolved"
            )
            self.assertIsNone(
                self._stored_percentage(rate),
                f"{code!r}@{era_start} ({cell}) must store no percentage",
            )
            self.assertEqual(rate.source_note.split(NOTE_SEPARATOR)[0], note)
            found[(code, era_start)] = note
        self.assertEqual(len(found), len(FRACTION_LIKE_CELLS))

    def test_a_fraction_like_note_carries_a_proposal_and_says_it_is_not_data(self):
        """The note has to be actionable without ever reading as loaded.

        A maintainer resolving one of these needs the verbatim cell and what
        the neighbouring eras of the same code read, in one place. The
        proposal has to be unmistakable, because the failure mode this exists
        to prevent is a guessed rate being filed as though the SRI had
        published it.
        """
        for code, era_start, cell, note in FRACTION_LIKE_CELLS:
            rate = self._rate(code, era_start)
            source_note = rate.source_note
            self.assertTrue(
                source_note.startswith(note),
                f"{code!r}@{era_start} ({cell}) must start with the cell text",
            )
            self.assertIn(NOT_DATA_MARKER, source_note)
            self.assertIn(PROPOSAL_MARKER, source_note)
            # The proposal is never mistaken for a stored percentage.
            self.assertIsNone(self._stored_percentage(rate))
            self.assertEqual(rate.percentage, 0.0)

    def test_the_proposal_names_what_the_same_code_reads_elsewhere(self):
        """``504G`` reads 25 in five eras, so its 0.25 is corroborated.

        ``322`` and ``504F`` are not: they read 1 or 2 and 25 or 28
        respectively, and never the value their fraction would give. Saying so
        is the difference between a note that helps and one that misleads.
        """
        expectations = {
            "322": ("1.75", False),
            "504F": ("13", False),
            "504G": ("25", True),
        }
        for code, (candidate, corroborated) in expectations.items():
            rate = self.env[RATE_MODEL].search(
                [
                    ("concept_id.code", "=", code),
                    ("unresolved", "=", True),
                    ("source_note", "like", f"%{candidate}%"),
                ]
            )
            self.assertTrue(rate, f"{code!r} note should mention {candidate}")
            marker = CORROBORATED_MARKER if corroborated else UNCORROBORATED_MARKER
            self.assertIn(
                marker,
                rate[0].source_note,
                f"{code!r} note must say whether x100 is corroborated",
            )

    def test_no_resolved_rate_sits_between_zero_and_one(self):
        """The rule that produced those eight, checked over the whole table.

        Every percentage the sheet states as a number is 0 or 1 or more, so a
        resolved rate in ``(0, 1)`` would mean the fraction rule had missed
        one. Stating it as an invariant rather than as eight names means the
        next workbook revision cannot quietly introduce another.
        """
        offenders = self.env[RATE_MODEL].search(
            [("unresolved", "=", False), ("percentage", ">", 0), ("percentage", "<", 1)]
        )
        self.assertEqual(
            offenders,
            self.env[RATE_MODEL],
            "A resolved rate below 1 is a fraction the sheet wrote as a "
            "number; it must be unresolved with the cell text kept",
        )

    def test_a_resolved_rate_is_never_below_the_xsd_minimum(self):
        """``porcentajeAirType`` bounds the emittable rate at 100.

        Cheap to assert over the whole table and it catches a scale error from
        the other direction -- a cell read as a fraction that happens to land
        in range.
        """
        for rate in self.env[RATE_MODEL].search([("unresolved", "=", False)]):
            self.assertGreaterEqual(rate.percentage, 0.0)
            self.assertLessEqual(rate.percentage, 100.0)

    def test_spot_values_read_straight_from_their_source_cell(self):
        """One rate per era, each naming the cell it came from.

        Cross-checking the whole import is what the counts above are for; this
        is the part a human can verify against the spreadsheet by eye, so it
        deliberately spans the 2009, 2010, 2012, 2015 and 2026 eras.
        """
        for code, era_start, cell, percentage, era_end in SPOT_VALUES:
            rate = self._rate(code, era_start)
            self.assertEqual(
                rate.percentage,
                percentage,
                f"Concept {code!r}, cell {cell}, era {era_start}: expected "
                f"{percentage}, read {rate.percentage}",
            )
            self.assertEqual(
                rate.date_end,
                era_end,
                f"Concept {code!r}, cell {cell}: wrong era end",
            )

    def test_prose_cells_keep_the_source_text_verbatim(self):
        """``E16``, ``E128`` and ``CU47``.

        The verbatim text is the only thing that lets a human resolve the rate
        later, so it is stored unshortened -- spaces, slashes and all.
        """
        for code, era_start, cell, note in SPOT_PROSE:
            rate = self._rate(code, era_start)
            self.assertTrue(rate.unresolved, f"{code!r}@{era_start} ({cell})")
            self.assertEqual(rate.source_note, note, f"{code!r}@{era_start} ({cell})")
            self.assertIsNone(self._stored_percentage(rate))

    def test_spot_descriptions_read_from_each_era_own_cell(self):
        """``DB5``, ``CT14``, ``CK15``, ``CF17``, ``BB13`` and ``AC6``.

        One description per era, each naming the cell it came from, spanning
        the 2009, 2012, 2014, 2015, 2020 and 2024 eras. Several of these codes
        are reworded between eras, so a spot check is the only way to notice
        if one era's wording had leaked onto another's row.
        """
        for code, era_start, cell, description in SPOT_DESCRIPTIONS:
            rate = self._rate(code, era_start)
            self.assertEqual(
                rate.description,
                description,
                f"Concept {code!r}, cell {cell}, era {era_start}",
            )
            self.assertEqual(
                rate.description,
                rate.description.strip(),
                f"Concept {code!r}, cell {cell}: description must be trimmed",
            )

    # Historical resolution ----------------------------------------------

    def test_a_historical_period_resolves_to_a_different_percentage(self):
        """``322`` at ``CG25`` reads 1, at ``E27`` reads 2.

        This is the acceptance criterion the whole temporal design exists
        for. If ``_applicable_on`` ever returned one flat rate for both a
        2016 and a 2026 day, the era blocks would have been collapsed into a
        single series and every historical ATS would silently file today's
        rate.
        """
        historical = self._applicable_on("322", date(2016, 3, 15))
        current = self._applicable_on("322", date(2026, 8, 6))
        self.assertEqual(len(historical), 1)
        self.assertEqual(len(current), 1)
        self.assertEqual(historical.percentage, 1.0)
        self.assertEqual(current.percentage, 2.0)
        self.assertNotEqual(
            historical.percentage,
            current.percentage,
            "A 2016 day and a 2026 day resolved to the same rate, so the "
            "era windows are not being honoured",
        )

    def test_a_day_before_the_first_window_resolves_to_nothing(self):
        """``DA2`` = ``DESDE 01/ENE/2009``: the catalog starts in 2009.

        A concept that predates the earliest era has no window to match, and
        the mixin must say so rather than return the nearest rate.
        """
        self.assertEqual(
            self._applicable_on("322", date(2008, 12, 31)), self.env[RATE_MODEL]
        )

    def test_the_boundary_day_belongs_to_the_newer_era(self):
        """Inclusive endpoints, on a boundary where the value really moves.

        ``303A`` reads 3 in the 2026-02-01 era (``T6``, ending 2026-02-28) and
        5 in the 2026-03-01 era (``O6``), so the last day of the old era and
        the first day of the new one resolve to different rates. If the
        windows were exclusive of either end, one of the two days would
        resolve to nothing, or both to the same rate.

        Note the 2026-08-01 era is *not* usable for this: the SRI opened a
        five-day window before 2026-08-06 without changing a single rate, so
        the split is invisible in the values. That is the source's doing and
        the rates are all in force throughout, which is why the boundary that
        does move a rate is the one asserted.
        """
        for day, expected in ((date(2026, 2, 28), 3.0), (date(2026, 3, 1), 5.0)):
            applicable = self._applicable_on("303A", day)
            self.assertEqual(
                len(applicable), 1, f"{day} resolved {len(applicable)} rates"
            )
            self.assertEqual(applicable.percentage, expected)

    # The two families, per era -------------------------------------------

    def test_the_code_registry_carries_no_era_scoped_text(self):
        """The concept model is a code registry and nothing else.

        ``description`` and ``family`` moved to the rate because the SRI
        reuses a code for a different concept in a different era. Leaving
        either on the concept would force one era's wording onto every era,
        which is the misrepresentation this correction removed. Asserting
        their absence is the regression guard: re-adding one is a step back.
        """
        fields = self.env[CONCEPT_MODEL]._fields
        self.assertNotIn("concept", fields)
        self.assertNotIn("family", fields)
        self.assertNotIn("description", fields)
        self.assertIn("code", fields)

    def test_every_rate_states_zero_or_one_of_the_two_families(self):
        """``family`` mirrors ``Tabla 15`` codes ``01`` / ``02``, and is
        optional.

        ``TABLA 15`` reads ``PAGO A RESIDENTE /ESTABLECIMIENTO PERMANENTE``
        and ``PAGO A NO RESIDENTE``, which is exactly the two families the
        sheet's own section headers spell. It is optional because 854 rates
        sit in an era whose block states no section at all -- see the next
        test. The field is never given a third value.
        """
        stated = self.env[RATE_MODEL].search([("family", "!=", False)])
        families = set(stated.mapped("family"))
        self.assertEqual(families, {"residente", "no_residente"})

    def test_the_854_rates_of_the_three_unlabelled_blocks_state_no_family(self):
        """Blocks ``CS``, ``CW`` and ``DA`` carry no ``Módulo`` column, and
        ``302`` sits one row above block ``AF``'s only header.

        Those four cases are the whole of it: 287 + 285 + 281 + 1 = 854 rate
        rows where the era states no family. They are left empty rather than
        filled from a neighbouring era, because borrowing another era's value
        is exactly the smoothing that made 44 codes look consistent when the
        sheet does not. ``401AA`` at ``CU47`` is one of them: its description
        names Germany, which is suggestive, but a suggestive description is
        not a section header.
        """
        unlabelled = self.env[RATE_MODEL].search([("family", "=", False)])
        self.assertEqual(len(unlabelled), 854)
        self.assertEqual(
            unlabelled,
            self.env[RATE_MODEL].search(
                [("date_start", "in", ("2012-01-01", "2010-06-01", "2009-01-01"))]
            )
            | self.env[RATE_MODEL].search(
                [("concept_id.code", "=", "302"), ("date_start", "=", "2024-04-01")]
            ),
        )

    def test_the_family_is_read_from_that_era_not_borrowed(self):
        """``501`` is ``no_residente`` from block 0 and ``residente`` in
        blocks 6 and 7.

        Blocks ``AF`` and ``AK`` state no ``CÓDIGOS PARA PAGOS A NO
        RESIDENTE`` header, so their ``5xx`` rows fall under the resident
        header. That is a missing header in the source, not a family change,
        and it affects 87 rows over the 44 ``5xx`` codes. It is recorded
        literally and pinned here rather than corrected, because correcting it
        would mean substituting an era's value for another era's statement --
        and the contradiction is more useful visible than tidied away.
        """
        newest = self._rate("501", date(2026, 8, 6))
        self.assertEqual(newest.family, "no_residente")
        for era in (date(2024, 4, 1), date(2024, 3, 1)):
            self.assertEqual(
                self._rate("501", era).family,
                "residente",
                f"Era {era} states no non-resident header; the resident one "
                f"is what that block says",
            )
        contested = self.env[RATE_MODEL].search(
            [("family", "=", "residente"), ("concept_id.code", "in", ("520G", "525"))]
        )
        self.assertEqual(
            sorted({rate.date_start for rate in contested}),
            [date(2024, 3, 1), date(2024, 4, 1)],
        )

    def test_a_resident_concept_states_its_family_in_every_labelled_era(self):
        """``303`` at ``E5``, under ``CÓDIGOS PARA PAGO A RESIDENTE``."""
        for era in (date(2026, 8, 6), date(2015, 3, 1), date(2013, 1, 1)):
            self.assertEqual(self._rate("303", era).family, "residente")

    # Description, per era ------------------------------------------------

    def test_a_reused_code_resolves_to_two_descriptions_and_one_concept(self):
        """The regression guard for this correction.

        The SRI reuses a code for a different concept: ``341`` is *Otras
        retenciones aplicables el 2%* through the 2012, 2013 and 2014-10 eras
        (``CU37``, ``CQ37``, ``CL59``) and *Impuesto único a la exportación de
        banano de producción propia - componente 2* from 2015-03 to 2019-11
        (``CG69``..``BR73``). ``303A`` is *Utilización o aprovechamiento de la
        imagen o renombre* in 2014-10 (``CL6``) and *Servicios profesionales
        prestados por sociedades residentes* from 2024-03 (``AN6`` onwards).

        One code, one concept, and two eras that must read differently. With
        the description on the concept this was impossible to represent; the
        timeless concept could only ever show one of the two.
        """
        for code, older, newer in (
            (
                "341",
                (date(2014, 10, 1), "Otras retenciones aplicables el 2%"),
                (
                    date(2019, 11, 1),
                    "Impuesto único a la exportación de banano de producción "
                    "propia - componente 2",
                ),
            ),
            (
                "303A",
                (
                    date(2014, 10, 1),
                    "Utilización o aprovechamiento de la imagen o renombre",
                ),
                (
                    date(2026, 8, 6),
                    "Servicios profesionales prestados por sociedades residentes",
                ),
            ),
        ):
            older_era, older_text = older
            newer_era, newer_text = newer
            self.assertEqual(
                self._rate(code, older_era).description,
                older_text,
                f"{code!r} in {older_era} must keep its own era's description",
            )
            self.assertEqual(
                self._rate(code, newer_era).description,
                newer_text,
                f"{code!r} in {newer_era} must keep its own era's description",
            )
            self.assertNotEqual(older_text, newer_text)
            # Still exactly one concept: the code is the identity, the text is
            # not.
            self.assertEqual(
                len(self.env[CONCEPT_MODEL].search([("code", "=", code)])), 1
            )

    def test_every_rate_carries_its_own_era_description(self):
        """No rate may have an empty description.

        Every one of the 3149 rows read a non-empty ``Concepto`` cell, so the
        field is required. A blank would mean a row whose concept text was
        lost rather than one the sheet never stated.
        """
        self.assertEqual(
            self.env[RATE_MODEL].search([("description", "in", (False, ""))]),
            self.env[RATE_MODEL],
        )

    def test_a_period_inside_a_concept_hole_resolves_to_nothing(self):
        """``343`` has no rate in force on 2016-01-15.

        The SRI drops the code for the whole 2014-10-01..2018-02-28 run. The
        hole is kept rather than filled, so the resolution for a day inside
        it returns nothing -- which the generation preflight turns into a
        named refusal instead of a borrowed rate.
        """
        self.assertTrue(SOURCE_ERA_HOLES["343"])
        hole_start, _hole_end = SOURCE_ERA_HOLES["343"][0]
        inside = date.fromordinal(hole_start.toordinal() + 60)
        self.assertEqual(self._applicable_on("343", inside), self.env[RATE_MODEL])
        self.assertEqual(
            self.env[RATE_MODEL]._temporal_gaps(
                [("concept_id", "=", self._concept("343").id)]
            ),
            SOURCE_ERA_HOLES["343"],
        )

    # Triangulation: prove the detectors fire.
    #
    # An integrity suite that only ever inspects healthy data proves nothing
    # about whether it would notice an unhealthy one. Each test below breaks
    # one invariant on purpose, inside the rolled-back transaction, and
    # asserts the matching check reports it.

    def test_the_constraint_rejects_a_percentage_on_an_unresolved_rate(self):
        """The failure this whole model exists to prevent.

        Concept ``310``'s prose cell must never become a rate. Writing a
        percentage onto an unresolved row is precisely the assumed value the
        design forbids, so the constraint has to reject it.
        """
        rate = self._rate("310", NEWEST_ERA)
        with self.assertRaises(ValidationError):
            rate.write({"percentage": 1.0})

    def test_the_constraint_rejects_a_resolved_rate_without_a_percentage(self):
        """The other direction: a rate cannot claim to be resolved and hold
        no value. Creating it is the shape a careless hand-edit takes."""
        with self.assertRaises(ValidationError):
            self.env[RATE_MODEL].create(
                {
                    "concept_id": self._concept("322").id,
                    "description": "Seguros y reaseguros (primas y cesiones)",
                    "date_start": "2016-06-01",
                    "unresolved": False,
                }
            )

    def test_the_constraint_accepts_a_parsed_zero(self):
        """``323E2`` proves the constraint does not confuse 0 with "unset".

        If it did, every exempt concept in the table -- 350 cells read ``0`` --
        would be unloadable, which would be a false positive that pushes
        people towards inventing a non-zero rate instead."""
        rate = self.env[RATE_MODEL].create(
            {
                "concept_id": self._concept("323E2").id,
                "description": "Rendimientos financieros depósito a plazo fijo exentos",
                "date_start": "2026-01-01",
                "percentage": 0.0,
                "unresolved": False,
            }
        )
        self.assertEqual(rate.percentage, 0.0)

    def test_gap_detection_detects_a_hole_in_a_concept_series(self):
        """Losing a rate leaves a hole the detector reports.

        This is what a truncated import looks like, and it is why the era
        holes above are pinned rather than tolerated everywhere: a hole
        nobody expected has to fail.
        """
        concept = self._concept("322")
        self._rate("322", date(2015, 3, 1)).unlink()
        gaps = self.env[RATE_MODEL]._temporal_gaps([("concept_id", "=", concept.id)])
        self.assertEqual(gaps, [(date(2015, 3, 1), date(2016, 4, 30))])

    def test_overlap_detection_detects_a_duplicated_era(self):
        concept = self._concept("322")
        rates = self.env[RATE_MODEL].search([("concept_id", "=", concept.id)])
        original = rates.filtered(lambda rate: rate.date_start == date(2015, 3, 1))
        clone = original.copy({"date_end": False})
        self.assertTrue(original._temporal_overlapping(clone))

    def test_the_concept_count_detector_notices_a_lost_concept(self):
        model = self.env[CONCEPT_MODEL]
        before = model.search_count([])
        self._concept("401PO").unlink()
        self.assertEqual(model.search_count([]), before - 1)
        self.assertNotEqual(model.search_count([]), CONCEPT_COUNT)
