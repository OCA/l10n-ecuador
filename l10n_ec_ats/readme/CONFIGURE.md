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

## Tax support (`codSustento`) is captured, then validated here

`account.move.l10n_ec_tax_support` and `res.partner.l10n_ec_tax_support` are
`Char(size=2)`, **not** dropdowns. That is deliberate, and it is what makes this
module's validation possible.

They used to be `Selection` fields fed by a Python label list, which silently
capped the codes a document could carry at whatever that list happened to
contain. It stopped at `13`, so `Tabla 5` codes `14` (*Valores facturados por
socios a operadoras de transporte*, in force from 2018-01-01) and `15` (*Pagos
efectuados por consumos propios y de terceros de servicios digitales*, from
2020-06-01) could not be recorded on a purchase at all. **The authority for the
code is the catalog; the field is only a capture.** `l10n_ec_ats` validates the
captured code against `Tabla 5` resolved for the period being reported, and its
rejection message lists the codes the catalog does accept — so the guidance a
user gets comes from the records and cannot go stale.

Two consequences worth knowing:

- **A code outside `Tabla 5` for the reported period is refused**, not filed.
  `Tabla 5` is effective-dated, so a code valid in 2018 is not valid in 2016.
- **The line-level `account.move.line.l10n_ec_tax_support` and the withholding
  wizard line keep their `Selection`.** They are dropdowns, and the wizard builds
  its label map from the wizard *line* field, so retyping `account.move` does not
  disturb it.

### `TAX_SUPPORT` in `l10n_ec_withhold` is a label list, and it can drift

`l10n_ec_withhold/models/data.py` holds `TAX_SUPPORT`, a Python literal of
`(code, label)` pairs used by those dropdowns. It is **not** the authority, and
**nothing keeps it in step with the catalog**. `14` and `15` were missing from it
until the retyping above — that drift is exactly what this paragraph exists to
stop recurring unnoticed.

Its descriptions are transcribed from `Catalogo_ATS.xls` / `TABLAS
REFERENCIALES`, the same source this module loads as records in
`data/ats_catalog_05.xml`, so the wording can be checked without guessing. If the
SRI publishes a further `Tabla 5` code, add it there **and** let the catalog do
the validating; the literal only needs to carry the label.

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

## The `ventas` block is aggregated, and its key is wider than the sheet's

`ventas` is the one ATS block the SRI rolls up: one row per client and document
type, with `numeroComprobantes` carrying the count and the bases and taxes the
totals of every document folded into it. `l10n.ec.ats.collector.collect_ventas`
and `collect_ventas_with_errors` read it that way.

**The row key is `(tpIdCliente, idCliente, tipoComprobante, tipoEmision)`.**
`CLAVE PRIMARIA (2)` marks the first three as general key components and does
not list `tipoEmision` at all. The ficha settles what that leaves open:

> se puede ingresar el mismo tipo de documento siempre que difiera de la
> emisión de un mismo cliente en el período informado

The same document type may be filed again for the same client in the same
period **provided the emission type differs** — which is only satisfiable if a
differing emission type produces a row of its own. Folding them would put a
`tipoEmision` in the file that is true of one document out of two, or of
neither, while `numeroComprobantes` claimed both.

The key is computed from the **values that reach the file**, not from the partner
record, so two client records carrying one identification aggregate into one row
instead of producing two rows with the same primary key.

### `tipoEmision` is read off the issuing journal

The signal is a record: `account.journal.l10n_latam_use_documents`, the field
core `l10n_ec` itself computes `l10n_ec_require_emission` from. A journal that
issues documents files electronically; one that does not files physically, which
is the same answer the ficha gives for *"when the emission question is not
activated, place emission type F"*.

`Tabla 20` rows are picked by a keyword from the row's own description rather
than by a code held in Python — the same seam `Tabla 14` uses above — so the code
that reaches the file is always the catalogue's. The suite pins that each keyword
selects exactly one row.

### A credit note is a row, not a minus sign

`monedaType` has `minInclusive 0.0`, so no `ventas` line may go negative, and
`detalleVentasType` has no element that could express a reversal except its
`tipoComprobante`. A refund is therefore filed **under its own document type**
with **absolute** amounts: the document type is what tells the SRI this reverses
a sale. Negating the amounts would produce a document the schema rejects.

The same catalogue row also decides the payment form. The ficha states that
`formaPago` *"no aplica para los tipos de comprobantes Notas de Crédito (04)"*,
so a credit-note row carries no `formasDePago` element at all.

### Two fields are deliberately absent

- **`baseImpExe`** — `detalleVentasType` has no exempt base element;
  `detalleComprasType` does. An exempt sale therefore reports every base at zero
  rather than inventing a bucket the document cannot carry.
- **`compensaciones`** — condicional, and its type would come from `Tabla 21`,
  which *is* loaded. Nothing in Odoo records an IVA compensation under the
  solidarity law or on electronic money, so there is no record to read it from and
  the key is omitted rather than filled with a default.

### `valorRetIva` and `valorRetRenta` are the retentions *we* issued

Only withholdings issued on the **sale** side are read
(`l10n_ec_withholding_type == "sale"` plus a sale-side tax group), so the
mirror-image purchase withholding a company may hold against the same document
never reaches a sales row. The two sides are different events with different ATS
elements: `valorRetIva` says what the client took off us, not what we took off a
supplier.

`valorRetRenta` resolves **no** `Tabla 3.10` rate, and deliberately so: unlike
`air`, this block has no per-concept breakdown, so there is nowhere to put a code
or a percentage and an unresolved rate cannot affect the total that is all the
schema can express here. `valorRetIva` is still checked against `Tabla 11` for
the reported day — a rate the SRI never published is reported, not filed.

### `formasDePago` is not part of the key

The payment form belongs to a **transaction**, not to a client, so it is not
constant across a group. The ficha settles what to do with that: *"when a single
transaction used more than one payment form, all of the payment forms used must
be reported"*, and `formaPago` is unbounded. The row therefore carries the
distinct forms of every document folded into it, in booking order, each resolved
through `Tabla 13` for the reported day.

### One filter the loaded catalogue cannot answer

The ficha requires `ventas/tipoComprobante` to be a `Tabla 4` code *"filtered by
`Código Secuencial Transacción` equal to 04, 05, 06, 07 and 19"* — the codes
`Tabla 2` publishes as sale identifications. **`Tabla 4` stores two different
columns for those two ideas**, and the purchase block's `codSustento`
cross-check already uses one of them. What the collector asserts is therefore the
part the catalogue can answer: that the code is a real `Tabla 4` row in force on
the reported day. The filter itself is recorded for ATS-11 rather than
approximated with a list of codes the module would then own.

### `parteRelVtas` is not asked of the consumer sentinel

The ficha displays `parteRel` only for the three identification types a person
or company can hold, and `ats.xsd` makes the element optional — so the element is
omitted for the final-consumer client rather than answered for it. Accepting that
client is the opposite of the purchase rule and equally deliberate: `Tabla 2`
publishes `9999999999999` as a sale identification, and the ficha's `idCliente`
validation names *Consumidor Final* as a value the field may hold. Refusing it
would make the most ordinary Ecuadorian sale impossible to file.


