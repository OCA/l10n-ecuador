from datetime import date, datetime, timedelta

from odoo.exceptions import ValidationError
from odoo.orm.model_classes import add_to_registry
from odoo.tests.common import TransactionCase


class TestL10nEcTemporal(TransactionCase):
    """Boundary semantics of the ``l10n.ec.temporal`` mixin.

    A window is inclusive of both endpoints: a record applies on ``d`` when
    ``date_start <= d`` and (``date_end`` is null or ``d <= date_end``).
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from .fake_models import L10nEcTemporalTestEntry

        add_to_registry(cls.registry, L10nEcTemporalTestEntry)
        cls.registry._setup_models__(cls.env.cr, [L10nEcTemporalTestEntry._name])
        cls.registry.init_models(
            cls.env.cr, [L10nEcTemporalTestEntry._name], {"models_to_check": True}
        )
        cls.addClassCleanup(cls.registry.__delitem__, L10nEcTemporalTestEntry._name)
        cls.model = cls.env[L10nEcTemporalTestEntry._name]

    def _entry(self, code, date_start, date_end):
        return self.model.create(
            {
                "code": code,
                "date_start": date_start,
                "date_end": date_end,
            }
        )

    # Boundaries of a closed window

    def test_applies_on_date_start(self):
        entry = self._entry("12", "2024-01-01", "2024-12-31")
        self.assertIn(entry, self.model._applicable_on(date(2024, 1, 1)))

    def test_applies_on_date_end(self):
        entry = self._entry("12", "2024-01-01", "2024-12-31")
        self.assertIn(entry, self.model._applicable_on(date(2024, 12, 31)))

    def test_applies_inside_window(self):
        entry = self._entry("12", "2024-01-01", "2024-12-31")
        self.assertIn(entry, self.model._applicable_on(date(2024, 7, 1)))

    def test_does_not_apply_before_date_start(self):
        entry = self._entry("12", "2024-01-01", "2024-12-31")
        day_before = date(2023, 12, 31)
        self.assertNotIn(entry, self.model._applicable_on(day_before))

    def test_does_not_apply_after_date_end(self):
        entry = self._entry("12", "2024-01-01", "2024-12-31")
        day_after = date(2025, 1, 1)
        self.assertNotIn(entry, self.model._applicable_on(day_after))

    # Open-ended window

    def test_null_date_end_applies_far_in_the_future(self):
        entry = self._entry("12", "2024-06-01", False)
        self.assertIn(entry, self.model._applicable_on(date(2024, 6, 1)))
        self.assertIn(entry, self.model._applicable_on(date(2199, 12, 31)))

    def test_null_date_end_does_not_apply_before_date_start(self):
        entry = self._entry("12", "2024-06-01", False)
        self.assertNotIn(entry, self.model._applicable_on(date(2024, 5, 31)))

    # Inverted window is a data error

    def test_date_start_after_date_end_raises(self):
        with self.assertRaises(ValidationError):
            self._entry("12", "2024-12-31", "2024-01-01")

    def test_single_day_window_is_valid(self):
        entry = self._entry("12", "2024-06-01", "2024-06-01")
        self.assertIn(entry, self.model._applicable_on(date(2024, 6, 1)))
        self.assertNotIn(entry, self.model._applicable_on(date(2024, 5, 31)))
        self.assertNotIn(entry, self.model._applicable_on(date(2024, 6, 2)))

    # Overlap detection

    def test_overlapping_partial_overlap(self):
        first = self._entry("A", "2024-01-01", "2024-06-30")
        second = self._entry("B", "2024-03-01", "2024-09-30")
        self.assertTrue(first._temporal_overlapping(second))
        self.assertTrue(second._temporal_overlapping(first))

    def test_overlapping_containment_both_directions(self):
        outer = self._entry("A", "2024-01-01", "2024-12-31")
        inner = self._entry("B", "2024-03-01", "2024-04-30")
        self.assertTrue(outer._temporal_overlapping(inner))
        self.assertTrue(inner._temporal_overlapping(outer))

    def test_overlapping_identical_windows(self):
        first = self._entry("A", "2024-01-01", "2024-12-31")
        second = self._entry("B", "2024-01-01", "2024-12-31")
        self.assertTrue(first._temporal_overlapping(second))

    def test_overlapping_open_ended_against_closed(self):
        opened = self._entry("A", "2024-01-01", False)
        closed = self._entry("B", "2030-01-01", "2030-12-31")
        self.assertTrue(opened._temporal_overlapping(closed))
        self.assertTrue(closed._temporal_overlapping(opened))

    def test_not_overlapping_adjacent_windows(self):
        first = self._entry("A", "2024-01-01", "2024-01-31")
        second = self._entry("B", "2024-02-01", "2024-02-29")
        self.assertFalse(first._temporal_overlapping(second))
        self.assertFalse(second._temporal_overlapping(first))

    def test_not_overlapping_far_apart_windows(self):
        first = self._entry("A", "2016-01-01", "2016-12-31")
        second = self._entry("B", "2024-01-01", "2024-12-31")
        self.assertFalse(first._temporal_overlapping(second))
        self.assertFalse(second._temporal_overlapping(first))

    def test_not_overlapping_open_ended_starts_after_closed_ends(self):
        closed = self._entry("A", "2016-01-01", "2016-08-31")
        opened = self._entry("B", "2016-09-01", False)
        self.assertFalse(closed._temporal_overlapping(opened))
        self.assertFalse(opened._temporal_overlapping(closed))

    # Gap detection

    def test_gaps_reports_hole_between_non_contiguous_entries(self):
        self._entry("310", "2024-01-01", "2024-01-31")
        self._entry("310", "2024-03-01", "2024-03-31")
        gaps = self.model._temporal_gaps([("code", "=", "310")])
        self.assertEqual(gaps, [(date(2024, 2, 1), date(2024, 2, 29))])

    def test_gaps_empty_for_contiguous_series(self):
        self._entry("310", "2024-01-01", "2024-01-31")
        self._entry("310", "2024-02-01", "2024-02-29")
        self._entry("310", "2024-03-01", "2024-03-31")
        self.assertEqual(self.model._temporal_gaps([("code", "=", "310")]), [])

    def test_gaps_empty_for_open_ended_tail(self):
        self._entry("310", "2016-01-01", "2016-08-31")
        self._entry("310", "2016-09-01", False)
        self.assertEqual(self.model._temporal_gaps([("code", "=", "310")]), [])

    def test_gaps_empty_for_single_open_ended_entry(self):
        self._entry("310", "2016-09-01", False)
        self.assertEqual(self.model._temporal_gaps([("code", "=", "310")]), [])

    def test_gaps_are_per_key(self):
        self._entry("310", "2024-01-01", "2024-01-31")
        self._entry("310", "2024-03-01", "2024-03-31")
        self._entry("311", "2024-01-01", "2024-01-31")
        self._entry("311", "2024-02-01", "2024-02-29")
        self.assertEqual(self.model._temporal_gaps([("code", "=", "311")]), [])
        self.assertEqual(
            self.model._temporal_gaps([("code", "=", "310")]),
            [(date(2024, 2, 1), date(2024, 2, 29))],
        )

    def test_gaps_ignores_other_series(self):
        self._entry("310", "2024-01-01", "2024-01-31")
        self._entry("310", "2024-03-01", "2024-03-31")
        self._entry("999", "1990-01-01", "1990-12-31")
        self.assertEqual(
            self.model._temporal_gaps([("code", "=", "310")]),
            [(date(2024, 2, 1), date(2024, 2, 29))],
        )

    def test_gaps_empty_for_unknown_key(self):
        self._entry("310", "2024-01-01", "2024-01-31")
        self._entry("310", "2024-03-01", "2024-03-31")
        self.assertEqual(self.model._temporal_gaps([("code", "=", "404")]), [])

    def test_gaps_survive_overlapping_entries(self):
        # Overlap is a separate invariant, checked by ``_temporal_overlapping``.
        # Gap detection must still walk forward monotonically and must never
        # invent a gap out of an entry nested inside another one.
        self._entry("310", "2024-01-01", "2024-12-31")
        self._entry("310", "2024-03-01", "2024-04-30")
        self._entry("310", "2025-02-01", "2025-03-31")
        self.assertEqual(
            self.model._temporal_gaps([("code", "=", "310")]),
            [(date(2025, 1, 1), date(2025, 1, 31))],
        )

    def test_gaps_report_hole_immediately_before_open_ended_entry(self):
        # September 2016 is covered by nothing: the closed entry stops on
        # 2016-08-31 and the open-ended one only starts on 2016-10-01. An
        # open-ended window bounds nothing forwards, but it still claims a
        # date_start, and the hole before it must not be silently dropped.
        self._entry("310", "2016-01-01", "2016-08-31")
        self._entry("310", "2016-10-01", False)
        self.assertEqual(
            self.model._temporal_gaps([("code", "=", "310")]),
            [(date(2016, 9, 1), date(2016, 9, 30))],
        )

    def test_gaps_report_long_hole_before_open_ended_entry(self):
        # Same shape, hole longer than a month, so the bounds come from the
        # two real endpoints rather than from an off-by-one that happens to
        # work on a single month.
        self._entry("310", "2016-01-01", "2016-01-31")
        self._entry("310", "2016-06-01", False)
        self.assertEqual(
            self.model._temporal_gaps([("code", "=", "310")]),
            [(date(2016, 2, 1), date(2016, 5, 31))],
        )

    def test_gaps_empty_for_contiguous_run_before_open_ended_tail(self):
        # Guard against over-firing: several closed entries in a row followed
        # by a contiguous open-ended tail must still report nothing.
        self._entry("310", "2016-01-01", "2016-01-31")
        self._entry("310", "2016-02-01", "2016-02-29")
        self._entry("310", "2016-03-01", False)
        self.assertEqual(self.model._temporal_gaps([("code", "=", "310")]), [])

    # Argument handling of _applicable_on

    def test_applicable_on_coerces_date_string(self):
        entry = self._entry("12", "2024-01-01", "2024-12-31")
        self.assertIn(entry, self.model._applicable_on("2024-07-01"))

    def test_applicable_on_normalizes_datetime(self):
        entry = self._entry("12", "2024-01-01", "2024-12-31")
        self.assertIn(entry, self.model._applicable_on(datetime(2024, 7, 1, 23, 59)))

    def test_applicable_on_empty_for_date_before_every_window(self):
        self._entry("12", "2024-01-01", "2024-12-31")
        self.assertFalse(self.model._applicable_on(date(2000, 1, 1)))

    def test_applicable_on_empty_for_date_after_every_window(self):
        self._entry("12", "2024-01-01", "2024-12-31")
        self.assertFalse(
            self.model._applicable_on(date(2024, 12, 31) + timedelta(days=1))
        )
