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

## Income withholding concepts (`Tabla 3.10`)

`Tabla 3.10` is split in two models, because the SRI **reuses a concept code
for a different concept from one era to the next**:

- `l10n.ec.ats.income.withholding.concept` is a **code registry and nothing
  else** — one field, `code`. It does **not** inherit `l10n.ec.temporal`:
  a code has no validity window, so it needs no sentinel date.
- `l10n.ec.ats.income.withholding.rate` carries everything the SRI says about
  a concept **within one era**: `description`, `family`, `percentage`, and the
  window from the `l10n.ec.temporal` mixin.

**Description and family are era-scoped. Read them from the rate, never from
the concept.** Code `341` is *Otras retenciones aplicables el 2%* through
2014 and *Impuesto único a la exportación de banano de producción propia -
componente 2* from 2015. Code `303A` is *Utilización o aprovechamiento de la
imagen o renombre* in the 2014-10 era and *Servicios profesionales prestados
por sociedades residentes* from 2024-03. 106 of the 414 codes carry a different
description in different eras, so a description on the concept would force
one era's wording onto every era — a fact the SRI does not state. Nothing is
merged, and no era borrows another era's value.

Read a rate through `_applicable_on(day)`, never directly. The ATS is filed
per month, and the description, the family and the rate that apply all depend
on that month.

### A period inside a concept's hole resolves to nothing

Fifteen concepts have an era hole: the SRI drops them from one era and brings
them back in a later one — `343` is absent for the whole 2014-10-01 to
2018-02-28 run. The holes are kept, not filled, because filling one would
mean publishing a rate for a period the SRI never stated.

**`_applicable_on` therefore returns no rate at all for a day inside a hole**,
not the nearest rate and not the previous era's. The generation preflight
turns that into a named refusal. A concept that simply did not exist before
its first appearance is not a hole — that is the mixin's documented behaviour,
since the span checked runs from the earliest `date_start`.

### `unresolved` rates are not errors

**1689 of the 3149 rates carry no percentage.** That is what the SRI
publishes: most cells of the table hold a range (`25 o 37`), a dash (`-`), a
list of CDI tariffs, or a legal reference. Those are imported with
`unresolved` set and the cell text kept verbatim in `source_note`. Guessing a
single number would produce a catalog that looks plausible and is silently
wrong, which is the one outcome worse than a refusal.

Do not resolve one of these by hand without the ficha tecnica. Concept `310`
in the newest era reads `1 /0 según resolución NAC-DGERCGC26-00000028`: the
cell names two candidate rates and the resolution holding the real one, and
picking either would be a guess dressed as data.

Eight cells read as numbers but are **not** percentages: `0.0175` (code
`322`), `0.13` (`504F`) and `0.25` (`504G`). They are rates written as
fractions — `504G` reads `0.25` in 2015 and 2016 and `25` from 2018 on — so
they are `unresolved` too. Reading `0.25` as a percentage would state a
quarter of one percent for a concept withheld at 25, and the wrong number
would look entirely plausible.

Their `source_note` carries three parts, in this order: the verbatim cell, the
candidate reading marked **NOT DATA, PROPOSAL ONLY**, and whether the same
code's other eras corroborate it. Only `504G` is corroborated — `322` and
`504F` read something else in every other era and never the value their
fraction would give. Read the note; do not read the candidate as a rate.

### `family` is optional, and empty where the era states none

`family` mirrors `Tabla 15`: `residente` is code `01` (*pago a residente /
establecimiento permanente*), `no_residente` is code `02` (*pago a no
residente*). The sheet states it as the section header a row sits under.

**854 rates state no family and carry none.** Blocks `CS`, `CW` and `DA` have
no `Módulo` column at all, and row `AG5` sits above block `AF`'s only header.
Those rows are left empty rather than filled from a neighbouring era: no era's
value belongs to another era's row. A description that names a foreign
country is suggestive, but a suggestive description is not a section header.

**Blocks `AF` and `AK` state no non-resident header**, so their 87 rows over
the 44 `5xx` codes read `residente` while nineteen other eras read
`no_residente`. That is a missing header in the source, not a family change.
It is recorded literally and pinned by the test suite rather than corrected,
because correcting it would mean substituting one era's value for another
era's statement. Treat the family of any `5xx` code in the 2024-03-01 to
2024-06-30 window with suspicion.

### Two other things the sheet does not support

- **Four codes carry a space.** `C37`..`C40` read `323 M` .. `323 P`, and
  `ats.xsd`'s `codRetAirType` (`[A-Za-z0-9]{3,5}`) rejects it, so those codes
  could never be emitted. The space is dropped, which is what the sheet's own
  sibling codes (`323A`, `323B1`, `323C`..`323K`, `323E`, `323E2`) already do.
  Nothing else about a code is touched: codes are opaque strings, never
  parsed as numbers.
- **One cell is empty.** `CL56`, code `335A` in the 2014-10 era. It is
  imported as `unresolved` with an empty `source_note`, which is the only
  honest reading and the only rate in the table with nothing to go on.


