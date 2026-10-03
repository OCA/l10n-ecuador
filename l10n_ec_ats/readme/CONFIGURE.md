Nothing to configure.

The module installs the `l10n.ec.temporal` abstract mixin and requires
`l10n_ec_base`, `l10n_ec_account_edi` and `l10n_ec_withhold` to be installed.
It adds no technical setting; the only user interface is the generation wizard,
reachable from **Invoicing ‣ SRI ‣ ATS**.

This document used to be one linear read of 620 lines, which is not a thing
anyone can act on. It is now in three tiers, and you only need to know which
one you are in:

| Tier | Read it when | Length |
| --- | --- | --- |
| **1 — Set this up** | You are installing the module and want to generate a month | ~1 screen |
| **2 — Know this about the catalog** | You touch catalog records, or a generation was refused for a catalog reason | ~4 screens |
| **3 — Block semantics** | You are reading or changing a collector | a table, then a pointer |

**Where the reasoning lives now.** Tier 3 does not restate *why* each block
behaves as it does — that would be a fourth copy of a decision that already has
to be kept in step with the code. Each rule points at its single home:

| Question | Home |
| --- | --- |
| Which Odoo record fills which ATS element? | [`DESIGN.md`](https://github.com/OCA/l10n-ecuador/blob/19.0/l10n_ec_ats/readme/DESIGN.md) — the mapping table, all five blocks |
| Why does this rule exist, and what was rejected? | [ADR 0002](https://github.com/OCA/l10n-ecuador/blob/19.0/l10n_ec_ats/docs/adr/0002-ats-design-decisions.md) |
| What is open, unstated or contradictory in the source? | [`ROADMAP.md`](https://github.com/OCA/l10n-ecuador/blob/19.0/l10n_ec_ats/readme/ROADMAP.md) |
| How do I generate, and what happens when it refuses? | [`USAGE.md`](https://github.com/OCA/l10n-ecuador/blob/19.0/l10n_ec_ats/readme/USAGE.md) |

---

# Tier 1 — Set this up

## A journal needs an establishment, and `001` is the floor

There is no `res.establishment` in `l10n-ecuador` nor in core `l10n_ec`, so an
ATS establishment is derived from the journal pair `account.journal`'s
`l10n_ec_entity` / `l10n_ec_emission`. Every EC company therefore needs those
set on the journals it sells from, or the `ventasEstablecimiento` block will not
carry those establishments — and `numEstabRuc` is the row count, so a missing
establishment shrinks the header too.

`000` is **never** valid. `l10n_ec_base` only checks length and `isnumeric()`,
so `"000"` passes its constraint today; the collectors, the builder and the
validators each refuse it independently. Tightening the upstream constraint is a
separate proposal — see `ROADMAP.md`.

## The tax support a purchase must carry

`account.move.l10n_ec_tax_support` is `Char(size=2)`, **not** a dropdown, and it
is **mandatory** on every document in the `compras` block. A purchase without
one is refused with a message naming the bill, because `Tabla 5` requires exactly
one code per document and ATS does not guess it. The rejection lists the codes
the catalog accepts **for the period being reported**, read from the records.

The field is a capture, not the authority — see *Tax support is captured, then
validated here* under Tier 2 below for why.

## The wizard

`l10n.ec.ats.generate` takes a `company_id`, an `anio` and a `mes`, and
`generate()` returns the action that downloads the archive. It opens from
**Invoicing ‣ SRI ‣ ATS** and stays usable from an automated action, RPC or a
shell.

- **`anio` and `mes` are integers, and the field refuses an impossible period.**
  `Catalogo_ATS.xls` / `ESQUEMA TIPO 1 Y 2` row 7 says the year *"debe
  corresponder a periodos del 2000 en adelante"* and the ficha's `ESQUEMA` adds
  *"Programa despliega calendario 2000 en adelante"*, so an earlier year is
  refused on the field rather than discovered in the document. The month is
  bounded by `mesType`'s own pattern.
- **`mes` is captured as a number, not chosen from a list.** The code that
  reaches the file is the `Tabla 01` row's own, read from the catalog, so the
  wizard cannot disagree with the table the moment the SRI republishes it.
- **`regimenMicroempresa` is derived, not configured.** It is emitted when the
  company declares a `l10n_ec_regimen` **and** the `Tabla 01` row of the
  reported month names a semestral regime — which is what the sheet's own
  descriptions say for the two semestral months and do not say for the other
  ten. No `{06, 12}` set is held in Python.
- **The company must be an EC one with a RUC.** `IdInformante` is
  `company.partner_id.vat`; the builder refuses an empty one, and ATS-11 applies
  the RUC module 11 check digit to it, so a wrong digit stops generation.
- **`warnings` is the report, not a blocker.** `generate()` writes every
  non-blocking finding there and the form shows it beside the download. A grave
  finding never reaches it — it stops generation, and every problem is listed in
  one `UserError` rather than only the first.

The wizard is a `TransientModel` and lives in `l10n_ec_ats/wizard/`, not in
`models/`: the repository's mandatory `pylint_odoo` run enables
`no-wizard-in-models`, which refuses a `TransientModel` declared under
`models/`. `l10n_ec_withhold/wizard/` and `l10n_ec_account_edi/wizard/` are the
existing precedent.

---

# Tier 2 — Know this about the catalog

The mixin's semantics — inclusive windows, open-ended `date_end`, gap and
overlap detection, the helper names — are in [`USAGE.md`](https://github.com/OCA/l10n-ecuador/blob/19.0/l10n_ec_ats/readme/USAGE.md) under
*Catalog semantics*. What follows is what a **catalog record** needs.

## Effective-dated catalog entries

Every `l10n.ec.ats.catalog.entry` carries a validity window. `date_start` is
the first day the entry applies to and `date_end` the last one, both
included; leaving `date_end` empty means the entry is still in force.

**The SRI publishes no validity date for the referred transaction types, for the
month codes, for `Tabla 14`, `Tabla 15`, or for `Tabla 4`** — the last one spells
its `Fecha de vigencia` column `vacío` in all forty rows. Those entries carry
`1900-01-01` in `date_start` as a **sentinel meaning "the source states no
date"**, not as a real start date, and their `date_end` is empty. Do not read
that date as business data and do not filter on it. `1900-01-01` was chosen over
a plausible-looking date such as `2000-01-01` precisely because a sentinel must
not be mistakable for real data; the full rationale, and the two rows whose real
dates *are* stated in prose footnotes, are in `ROADMAP.md`.

## Catalog tables

`l10n.ec.ats.catalog.table` is the registry. `entry_count` is the coverage
manifest: how many rows the source spreadsheet has for that table, asserted
against the loaded entries by the test suite so a truncated import cannot
pass silently. `source_reference` names the sheet and row range every value
came from.

**Table numbers are stored zero-padded** (`01`, `02`, `05`), and so are the entry
codes of `Tabla 01`, `Tabla 02`, `Tabla 05` and `Tabla 13`. `Tabla 04` and
`Tabla 11` store their entries **unpadded** (`1`, `9`, `10`). An unpadded table
number matches nothing, and a lookup that matches nothing resolves to *absent*
rather than raising — the worst shape a lookup failure can take, because a rate
silently becomes "no rate" instead of an error.

## Tax support is captured, then validated here

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
  a concept **within one era**: `description`, `family`, `percentage`,
  `detail_group`, and the window from the `l10n.ec.temporal` mixin.

**Description, family and grouping are era-scoped. Read them from the rate,
never from the concept.** Code `341` is *Otras retenciones aplicables el 2%*
through 2014 and *Impuesto único a la exportación de banano de producción propia -
componente 2* from 2015. Code `303A` is *Utilización o aprovechamiento de la
imagen o renombre* in the 2014-10 era and *Servicios profesionales prestados por
sociedades residentes* from 2024-03. 106 of the 414 codes carry a different
description in different eras, so a description on the concept would force one
era's wording onto every era — a fact the SRI does not state. Nothing is merged,
and no era borrows another era's value.

Read a rate through `_applicable_on(day)`, never directly. The ATS is filed
per month, and the description, the family, the rate and the sub-report group that
apply all depend on that month.

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

`fields.Float` reads a NULL column back as `0.0`, so `unresolved` and a
legitimately exempt `0%` rate are indistinguishable in the ORM. The consistency
constraint reads the stored column directly; see
`l10n.ec.ats.income.withholding.rate._check_percentage_matches_unresolved`.

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

### `detail_group` names a sub-report; it never carries a code

`l10n.ec.ats.income.withholding.rate.detail_group` is a `Selection` of **group
names** — `dividend`, `banana`, or empty. It is loaded from
`data/ats_income_withholding_rates.xml`, on the 99 of the 3149 rate rows it
applies to, and it exists because
`validators.validate_compras_row` **raises** `ValueError` when an `air` row
carries one of the five conditional elements and the caller supplied no
`AirConditionalCodes`: a check that cannot be made must not be allowed to look
covered.

`Catalogo_ATS.xlsx` carries **no column** saying which `codRetAir` needs which
sub-report, and it cannot be derived from the concept either. The SRI reuses a
code across eras:

| Code | Before 2015-03-01 | From 2015-03-01 |
| --- | --- | --- |
| `340` | *Otras retenciones aplicables el 1%* | *Impuesto único a la exportación de banano de producción propia - componente 2* |
| `341` | *Otras retenciones aplicables el 2%* | the same, componente 2 |
| `342` | *Otras retenciones aplicables el 8%* | *Impuesto único a la exportación de banano producido por terceros* |
| `327` | *Por venta de combustibles a comercializadoras* | *Dividendos distribuidos a personas naturales residentes* |

A timeless list of codes would file a banana sub-report against a 2013 concept
that was not one, and would file none at all for the concept that was. So the
grouping is a **dated fact about an era**, which is why it lives on the rate —
the model that already carries the window — and not on the concept, which is a
code registry with no dates at all.

**The candidate set is the ficha's eight codes; each era is then kept only when
that era's own description names the thing.** Eighteen of the 117 eras of those
codes do not, and they carry no group on purpose. Three codes have an era hole
the SRI itself created — `330`, `341` and `342` are dropped from 2020 — so they
are in no group for a current period, and the wizard resolves that from the data
rather than from a list.

Read it as `rate.detail_group` **after** resolving the rate for the reported
period. Never from the concept: a concept has no window to resolve against.
The reasoning, and the two things about it a maintainer should look at, are in
`DESIGN.md` §2.1 and `ROADMAP.md`.

---

# Tier 3 — Block semantics

One row per block, one line per rule, and a pointer to where the rule is
derived. The full element-by-element mapping is in [`DESIGN.md`](https://github.com/OCA/l10n-ecuador/blob/19.0/l10n_ec_ats/readme/DESIGN.md); the
decisions behind these rules are in
[ADR 0002](https://github.com/OCA/l10n-ecuador/blob/19.0/l10n_ec_ats/docs/adr/0002-ats-design-decisions.md).

## `compras`

| Rule | Where it comes from |
| --- | --- |
| One row **per document**; a document with any error yields **no** row | `DESIGN.md` §2 |
| `establecimiento` / `puntoEmision` / `secuencial` are the **supplier's** triple, from `l10n_latam_document_number`, with the access key `[24:39]` as the documented recovery path | ADR 0002 §11 |
| `autorizacion` is **refused**, never `'9999999999'` | ADR 0002 §11, §12 |
| All six `Tabla 11` elements are emitted, defaulting to `0.00` — a **sourced** zero, because the catalog published no withholding at that rate | `DESIGN.md` §2 |
| Amounts are **absolute**: `monedaType` has `minInclusive 0.0`, so a credit note is reduced, not negated | ADR 0002 §11 |
| `air` is `minOccurs="0"`: no withholding means **no element**, never an empty one | ADR 0002 §6 |
| `000` is refused on both three-digit halves, though `ats.xsd` accepts it there | ADR 0002 §8 |

## `ventas`

| Rule | Where it comes from |
| --- | --- |
| **Aggregated**, one row per `(tpIdCliente, idCliente, tipoComprobante, tipoEmision)` — the sheet marks three key components and does not list `tipoEmision`; the ficha settles the gap: *"se puede ingresar el mismo tipo de documento siempre que difiera de la emisión de un mismo cliente en el período informado"* | `DESIGN.md` §3 |
| The key is computed from the **values that reach the file**, so two client records carrying one identification aggregate into one row | `DESIGN.md` §3 |
| `tipoEmision` is read off the issuing journal's `l10n_latam_use_documents` — *"when the emission question is not activated, place emission type F"* | `DESIGN.md` §3 |
| A credit note is a **row, not a minus sign**: filed under its own `tipoComprobante` with absolute amounts, and with **no** `formasDePago` (*"no aplica para los tipos de comprobantes Notas de Crédito (04)"*) | ADR 0002 §11, §6 |
| **`baseImpExe` is absent** — `detalleVentasType` has no exempt base element, so an exempt sale reports every base at zero | `DESIGN.md` §3 |
| **`compensaciones` is absent** — `Tabla 21` *is* loaded; nothing in Odoo records an IVA compensation, so the key is omitted rather than defaulted | `DESIGN.md` §3, §7 |
| `valorRetIva` / `valorRetRenta` are what the **client** withheld: only sale-side withholdings are read, so the mirror-image purchase withholding never reaches a sales row | `DESIGN.md` §3 |
| `valorRetRenta` resolves **no** `Tabla 3.10` rate, deliberately — the block has no per-concept breakdown, so there is nowhere to put a code or a rate | `DESIGN.md` §3 |
| `formasDePago` is **not** part of the key: *"when a single transaction used more than one payment form, all of the payment forms used must be reported"*, and `formaPago` is unbounded | `DESIGN.md` §3 |
| `parteRelVtas` is **omitted** for the final-consumer sentinel — `ats.xsd` makes it optional and the ficha displays it only for three identification types | `DESIGN.md` §3 |
| One filter the loaded catalog **cannot** answer: `ventas/tipoComprobante` must be *"filtered by `Código Secuencial Transacción` equal to 04, 05, 06, 07 and 19"*, and `Tabla 4` stores two different columns for those two ideas. What is asserted is the part the catalog can answer — that the code is a real `Tabla 4` row in force on the reported day | `DESIGN.md` §3 |

## `ventasEstablecimiento`

| Rule | Where it comes from |
| --- | --- |
| `codEstab` is a **composite derivation** over records that do exist, because there is no `res.establishment` in `l10n-ecuador` nor in core `l10n_ec`. It is the single seam to replace if an establishment model ever lands | ADR 0002 §7 |
| The code is the **union** of the distinct `l10n_ec_entity` over the company's **active** journals and the entity segment of `l10n_latam_document_number` on the period's **posted sales** documents. Change a journal's entity after a document was issued and reading only the journals drops a real establishment from the count | `DESIGN.md` §4 |
| Two asymmetries are deliberate: **sales documents only** (a vendor bill carries the *supplier's* triple), and **sales journals are not special-cased** (`numEstabRuc` counts *establecimientos inscritos en el RUC*, so a purchase journal's establishment counts too) | `DESIGN.md` §4 |
| A journal with an **empty** `l10n_ec_entity` is skipped, not emitted — `l10n_ec_withhold/data/template/account.journal-ec.csv` seeds `sale_withhold_ec` that way, and it is active in every EC company | `DESIGN.md` §4 |
| An establishment that sold nothing still gets a row at `0.00`: *"debe generarse igual número de registros que el valor informado en el campo número de establecimientos del sujeto pasivo, inscritos en el RUC"* | `DESIGN.md` §4 |
| **`ventasEstab` is net, `totalVentas` is gross**, and the ficha's ceiling binds only when a credit note exists. `ventasEstab` may be negative and is **not** clamped | ADR 0002 §2 |
| `totalVentas` is read out of the `ventas` rows and **never** re-aggregated — `ESQUEMA` row 10 calls it a *casillero no editable* | ADR 0002 §2 |
| `numEstabRuc` is **zero-padded to three digits** (`\d{3}`), so seven establishments are `007`, never `7`. A count of zero has no valid representation and blocks rather than emitting `000` | ADR 0002 §8 |
| `ivaComp` is omitted for the same reason as `compensaciones`, and `ats.xsd` makes it `minOccurs="0"` | `DESIGN.md` §4, §7 |

## `anulados`

| Rule | Where it comes from |
| --- | --- |
| The only block that files a **range**, and the only one with **no date at all** — no `fechaEmision`, no `fechaRegistro`. All six of its elements are obligatory | `DESIGN.md` §5 |
| **One row per contiguous run.** *"Se debe considerar que se considerarán anulados los comprobantes que consten dentro del rango informado"* — so cancelling 5, 6, 7 and 9 is **two** rows, never one `5`–`9` row | ADR 0002 §4 |
| The row key is **`(establecimiento, puntoEmision, tipoComprobante, autorizacion)`** — `CLAVE PRIMARIA (2)` rows 196–201 mark all six elements as *componente de clave general*, and keying on the authorization is what guarantees it belongs to **every** document in the range | ADR 0002 §4 |
| `tipoComprobante` is the cancelled document's **own** `Tabla 4` code — *"uno de los códigos de la tabla 4, **sin filtro alguno**"*. The plausible alternative, `Tabla 4` code `18`, is rejected on three counts: it excludes credit and debit notes **by name**, `Tabla 2` code `18` (*"COMPROBANTES ANULADOS"*) is unreachable because this block has no `tpIdProv`, and a fixed code would have to live in Python | `DESIGN.md` §5, ADR 0002 §12 |
| `secuencialFin` **repeats** `secuencialInicio` for a run of one | ADR 0002 §3 |
| The ESQUEMA sheet spells this block's sixth element `autorización`, **with** an accent; the schema spells it `autorizacion`. The schema wins — it is what the file has to satisfy | `DESIGN.md` §5 |
| Selection: `move_type in ('out_invoice','out_refund')`, `state == 'cancel'`, `company_id`, and `move.date` inside the reported window | `DESIGN.md` §5 |
| **`posted_before` excludes the cancelled draft.** `button_cancel` accepts a draft and sets `state = 'cancel'`, so `state` alone admits a document that was never issued, never authorized and never numbered — and Odoo shows it as `/` | `DESIGN.md` §5 |
| `move.date` is the only selection date the block has, and the window is still checked against the reported month with the same rule the other blocks use. The error carries `field: "fechaRegistro"` because the block inherits the period requirement from document selection rather than from a field it does not emit | `DESIGN.md` §5 |
| A refused `000` takes the **whole document** out, never part of it, and a sequential that is not a number is refused too — this block is the only reason to check, because a range is opened and closed by comparing one sequential with the next | `DESIGN.md` §5, ADR 0002 §8 |
| **Not selected, and not implementable:** the ficha §2.5 excludes *"los comprobantes dados de baja a través del portal transaccional SRI en línea"*, and **no Odoo field records that** | `ROADMAP.md` |
| Every error carries all four keys — `move`, `journal`, `field`, `message`. Nothing in this block is a journal-level problem, so `journal` is always `False`; the key is present so a consumer can read either without a `KeyError`. The two blocks before this one build their dicts without `journal` | `ROADMAP.md` |
| Whether cancelled **withholdings** belong in this block is an open maintainer question, with Enterprise's treatment quoted as the reference for a future version | `ROADMAP.md` |

## The `air` sub-report

One row per income-withholding basis line; `air` is `maxOccurs="1"` holding
unbounded `detalleAir`, so a document with several concepts carries them all in
one row. `codRetAir` is `account.tax.l10n_ec_code_ats` on the **tax**, not on
the tax group — every withholding group shares a generic `"1"`/`"2"`
`l10n_ec_xml_fe_code` that says nothing about which concept was withheld.
`porcentajeAir` is resolved from the `Tabla 3.10` rate for the reported period,
and an unresolved rate is reported rather than completed.

The five conditional elements — `fechaPagoDiv`, `imRentaSoc`, `anioUtDiv`,
`numCajBan`, `precCajBan` — are the sub-report groups, loaded as era-scoped
`detail_group` data. See
the `detail_group` section under Tier 2
above for the code table and why the grouping cannot be timeless, and ADR 0001
§9 for the rejected alternatives.