Nothing to configure.

The module installs the `l10n.ec.temporal` abstract mixin and requires
`l10n_ec_base`, `l10n_ec_account_edi` and `l10n_ec_withhold` to be installed.
It exposes no user interface and adds no technical setting.

## Effective-dated catalog entries

Every `l10n.ec.ats.catalog.entry` carries a validity window. `date_start` is
the first day the entry applies to and `date_end` the last one, both
included; leaving `date_end` empty means the entry is still in force.

The SRI publishes no validity date for the referred transaction types, for
the month codes, for `Tabla 14`, `Tabla 15`, or for `Tabla 4` — the last one
spells its `Fecha de vigencia` column `vacío` in all forty rows. Those
entries carry `1900-01-01` in `date_start` as a **sentinel meaning "the
source states no date"**, not as a real start date, and their `date_end` is
empty. Do not read that date as business data and do not filter on it.

## Catalog tables

`l10n.ec.ats.catalog.table` is the registry. `entry_count` is the coverage
manifest: how many rows the source spreadsheet has for that table, asserted
against the loaded entries by the test suite so a truncated import cannot
pass silently. `source_reference` names the sheet and row range every value
came from.
