from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import ValidationError

ONE_DAY = timedelta(days=1)


class L10nEcTemporal(models.AbstractModel):
    """Mixin for the effective-dated catalogs of the SRI ATS specification.

    The SRI referential tables are not flat lists of codes: each entry is
    valid only during a window of time, and the applicable version depends on
    the period the ATS is filed for. Odoo 19 cannot express that -- ``account.tax``
    has no ``fields.Date`` at all -- so a rate change is modelled by duplicating
    the record and archiving it, which leaves the history unqueryable.

    Inheriting models get two fields and the helpers that the catalog integrity
    checks and the generation wizard need:

    * :meth:`_applicable_on` resolves the entry in force on a given day.
    * :meth:`_temporal_overlapping` detects two entries claiming the same day.
    * :meth:`_temporal_gaps` detects a period nobody covers.

    Boundary rule, identical in all three helpers: **a window is inclusive of
    both endpoints**. A record applies on day ``d`` when
    ``date_start <= d`` and (``date_end`` is null or ``d <= date_end``), so
    ``2024-01-31`` followed by ``2024-02-01`` is a contiguous series and not a
    gap. A null ``date_end`` is **open-ended** -- still in force -- and never
    invalid.
    """

    _name = "l10n.ec.temporal"
    _description = "Ecuadorian effective-dated record"

    date_start = fields.Date(
        string="Start Date",
        required=True,
        index=True,
        help="First day the entry applies to, included.",
    )
    date_end = fields.Date(
        string="End Date",
        index=True,
        help="Last day the entry applies to, included. "
        "Leave empty when the entry is still in force.",
    )

    @api.constrains("date_start", "date_end")
    def _check_temporal_window(self):
        """Reject an inverted window.

        ``date_start > date_end`` is a data error, not a boundary case: it
        describes a period of zero length that can never apply to any day.
        A null ``date_end`` is open-ended and always valid.
        """
        for record in self:
            if record.date_end and record.date_start > record.date_end:
                raise ValidationError(
                    self.env._(
                        "The start date %(start)s must not be later than the "
                        "end date %(end)s.",
                        start=fields.Date.to_string(record.date_start),
                        end=fields.Date.to_string(record.date_end),
                    )
                )

    @api.model
    def _applicable_on(self, date):
        """Return the records of this model applicable on ``date``.

        The window is inclusive of both endpoints: a record matches when
        ``date_start <= date`` and (``date_end`` is null or
        ``date <= date_end``). A null ``date_end`` matches any date from
        ``date_start`` onwards, however far in the future.

        ``date`` accepts a :class:`datetime.date` or a string in the ORM date
        format. A :class:`datetime.datetime` is **normalized** to its
        :meth:`~datetime.date.date` part -- the time of day and the timezone
        are discarded, because the fields being compared are dates.

        Record rules apply, so this resolves what ``self.env`` can read.
        Callers resolving a catalog entry for a period must therefore also
        assert the result holds exactly one record: zero means a coverage
        hole, more than one an overlap. Neither is silently tolerated.
        """
        day = fields.Date.to_date(date)
        return self.search(
            [
                ("date_start", "<=", day),
                "|",
                ("date_end", "=", False),
                ("date_end", ">=", day),
            ]
        )

    def _temporal_overlapping(self, other):
        """Return whether this window intersects ``other``.

        Two windows overlap when they share at least one day, the endpoints
        included. That covers partial overlap, containment in either
        direction, identical windows and any combination with an open-ended
        side. Windows that merely touch by adjacency -- ``2024-01-31`` and
        ``2024-02-01`` -- do **not** overlap, because the first day of the
        second window is the day after the last day of the first.

        Both operands must hold exactly one record. An open-ended window
        bounds nothing, so it only fails to overlap when the other window is
        closed and ends strictly before it starts.
        """
        self.ensure_one()
        other.ensure_one()
        if self.date_end and other.date_start > self.date_end:
            return False
        if other.date_end and self.date_start > other.date_end:
            return False
        return True

    @api.model
    def _temporal_gaps(self, key):
        """Return the day ranges of one series that no record covers.

        ``key`` is the caller-supplied identity of the series, as an ORM
        domain: ``[("code", "=", "310")]`` for a catalog code, or
        ``[("concept_id", "=", concept.id)]`` for an income withholding
        concept. The mixin deliberately knows nothing about what a series is
        keyed on, so the domain is what defines "same key" -- a composite key
        being just as expressible as a scalar one.

        The span checked runs from the earliest ``date_start`` of the series
        to the latest ``date_end``. Both ends are covered by construction:
        the earliest ``date_start`` is day one of a window, and an open-ended
        window extends past any day worth checking. Only holes *between*
        entries can therefore be reported, which is what the "no internal
        gaps" invariant of the coverage manifest is about.

        :return: a list of ``(date, date)`` tuples, each closed range of
            uncovered days, ordered by start date. Empty when the series is
            contiguous, when it is a single entry, or when no entry matched.
        """
        gaps = []
        entries = self.search(key, order="date_start, id")
        if not entries:
            return gaps
        # The series starts covered: the first day of the earliest window
        # belongs to that window, endpoints included.
        next_free = entries[0].date_start
        for entry in entries:
            if entry.date_start > next_free:
                gaps.append((next_free, entry.date_start - ONE_DAY))
            if not entry.date_end:
                # Open-ended: coverage extends past every day we can check,
                # but only from this entry's date_start onwards -- hence the
                # hole ahead of it is assessed above, before stopping here.
                break
            next_free = max(next_free, entry.date_end + ONE_DAY)
        return gaps
