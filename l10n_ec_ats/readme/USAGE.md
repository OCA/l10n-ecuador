This module currently ships only the `l10n.ec.temporal` mixin and its tests.
There is nothing to configure and no menu, no wizard and no catalog data yet:
the SRI referential tables are loaded by a later task of the same project.

The semantics the rest of the ATS work depends on are these:

- A window is **inclusive of both endpoints**. A record applies on date `d`
  when `date_start <= d` and (`date_end` is null or `d <= date_end`).
- A null `date_end` means **open-ended**, not "invalid". It applies
  arbitrarily far into the future.
- `date_start > date_end` is a **data error** and raises a `ValidationError`.
- Two windows **overlap** when they share at least one day. `2024-01-31` and
  `2024-02-01` are adjacent, not overlapping.
- The union of the windows of one series should be **contiguous**. A hole
  means a period the SRI covered and the catalog does not.

Models that inherit the mixin gain `date_start` and `date_end` fields plus:

- `_applicable_on(date)`: the recordset applicable on `date`.
- `_temporal_overlapping(other)`: whether two windows intersect.
- `_temporal_gaps(key)`: the uncovered ranges inside one series, where `key`
  is the caller-supplied domain identifying the series.