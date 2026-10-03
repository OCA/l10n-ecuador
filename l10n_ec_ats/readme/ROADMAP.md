# Roadmap

Two tables live here: what is **not** in the catalog yet, and why, and the
open questions a maintainer has to decide.

## Referential tables that are deliberately not loaded

Only the tables an in-scope ATS block needs are loaded. The rest exist in
`Catalogo_ATS.xls` and serve blocks the feature document excludes, so
loading them would be speculative: entries nobody reads, that a completeness
check then has to vouch for. Each is listed here with the sheet it lives in
and its row count, so a later version knows exactly what is missing.

Row counts are the number of data rows in the source, counted from the cells
named. They are not entry counts: a later import must re-derive them.

| Table | Title | Sheet | Rows | Cells | Why not loaded |
| --- | --- | --- | --- | --- | --- |
| `3.10` | Conceptos de retención en la fuente de impuesto a la renta (AIR) | `TABLAS RETENCIONES` | 291 | `B1`–`DC291` | 23 side-by-side date eras of income-withholding concepts and rates. Genuinely relational and resolved per line, so it needs its own `concept` / `rate` models rather than a table code. That is `ATS-01b`, not this task. |
| `6` | Distrito aduanero | `TABLAS REFERENCIALES` | 14 | `B118:C131` | Customs district, used by the export block. Exports are deferred on a data-model gap, not a policy one. |
| `7` | Código régimen (hasta septiembre 2012) | `TABLAS REFERENCIALES` | 44 | `B136:C179` | Pre-2012 customs regime, same export block. |
| `7.1` | Código régimen (desde octubre 2012) | `TABLAS REFERENCIALES` | 9 | `E136:F145` | Current customs regime, same export block. |
| `8` | Tarjetas de crédito | `TABLAS REFERENCIALES` | 5 | `B184:C188` | Card brand, used by `RECAP`. `RECAP` is a Tipo 2 contributor block. |
| `9` | Tipos fideicomiso | `TABLAS REFERENCIALES` | 19 | `B193:F211` | Trust type, used by the trusts/funds block. |
| `10` | Tipo de exportación / ingreso del exterior | `TABLAS REFERENCIALES` | 3 | `B216:E218` | Export / foreign-income kind, same export block. |
| `16` | Países | `TABLAS REFERENCIALES` | 260 | `B278:G364` | Three country pairs per row across 87 rows. Export block. |
| `17` | Paraísos fiscales | `TABLAS REFERENCIALES` | 88 | `B369:H456` | Tax havens, used by the foreign-regime block. |
| `18` | Tipos de ingresos del exterior | `TABLAS REFERENCIALES` | 39 | `B461:F499` | Foreign-income kind, same export block. |
| `19` | Tipos de régimen fiscal del exterior | `TABLAS REFERENCIALES` | 3 | `B504:D506` | Foreign tax regime, same export block. |

`Tabla 3.10` also remains unreconciled against
`l10n_ec_base/data/account_tax_group_data.py`: its 162 concepts do not
reconcile with the 17 tax groups there, and all nine VAT groups carry the
same XML FE code `"2"`. That is stated, not resolved — see the open questions
below.

## Open questions

### `totalVentas`: what does *"Solo Facturación Física F"* qualify?

`ESQUEMA TIPO 1 Y 2` row 10 defines the header's `totalVentas` and then appends a
clause that is explained nowhere in the workbook, the ficha técnica, or
`ats.xsd`. Verbatim:

> Casillero no editable, debe ser igual a la sumatoria de los valores registrados
> en los campos baseNoGraIva, Base Imponible y baseimpGrav. **Solo Facturación
> Física F**

The column is `Validaciones`, so unlike a footnote it is a rule — yet a
conditional on `tipoEmision` sitting in a *header* field is odd, because the
header has no emission type: emission is reported per row of the `ventas` block,
and a single period legitimately mixes electronic and physical issuance.

Three readings are possible and nothing in the sources chooses between them:

1. **Scoping the whole rule to physical issuance.** The three-bucket derivation
   applies only when `tipoEmision` is `F` for the period, and electronic
   invoicing derives `totalVentas` some other way this project has not found.
2. **A leftover from an earlier edition**, when the ATS covered only physical
   invoicing. Nothing in the row's other clauses reads as edition-specific.
3. **A constraint on which rows may be summed** — e.g. that a physical-only
   period may not mix emission types — rather than on the total itself.

**What ATS does, and why.** It applies reading 1's *derivation* literally and
derives `totalVentas` as the sum of the three buckets over the `ventas` rows for
the reported period, with no conditional on `tipoEmision`. That is the reading
the fiche técnica's own prose supports independently — *"corresponde a la suma de
los valores registrados en los campos: base Imponible IVA 0%, base Imponible IVA
tarifa diferente de 0% y base Imponible no objeto de IVA"* — with no emission
condition attached.

Guessing reading 2 or 3 instead would mean inventing a derivation the SRI never
published, which is the one thing this module refuses to do. **ATS-11 must
resolve this before the wizard can be called complete for an electronic
period.** If reading 1 is right, an electronic period's `totalVentas` is
currently wrong, and no test in this suite would catch it because the suite
cannot know the alternative.

Note the two sheets of the workbook agree verbatim: `ESQUEMA TIPO 1 Y 2` row 10
and `ESQUEMA REGIMEN RIMPE` row 11 carry the same clause. It is not a typo in
one sheet.

### The `000` establishment hole in `l10n_ec_base`

`account.journal._constrains_l10n_ec_entity_emission`
(`l10n_ec_base/models/account_journal.py:14-36`) checks only
`len(value) < 3` and `not value.isnumeric()`:

```python
if len(rec.l10n_ec_entity) < 3 or not rec.l10n_ec_entity.isnumeric():
```

**`"000"` satisfies both and is accepted today.** A user can set an establishment
of `000` on a journal and `l10n_ec_ats` will faithfully propagate it into the
ATS — which is why the collector refuses it itself rather than trusting the
constraint.

Verified across the shipped data: `l10n_ec_base` seeds `purchase_liquidation_ec`
`001/001`; `l10n_ec_withhold` seeds `purchase_withhold_ec` `001/001` and
`sale_withhold_ec` with an **empty** entity and emission; the EC chart template
creates no journal establishment at all. **No journal in any fixture or seed row
is set to `000`** — the hole is only reachable by hand.

The one-line tightening is a separate proposal against `l10n_ec_base`, which is
already merged (PR #101), so it cannot travel in this addon's PR.

### Two `account.tax` rows carry an ATS code that resolves to nothing

`account.tax.l10n_ec_code_ats` is the source of `codRetAir` — the feature
document's §5.3 corrected the field's own help text, which claims it conforms
to `Tabla 5`; it does not, it holds `Tabla 3.10` concept codes. Two rows in the
upstream `ec` chart template carry a code **`Tabla 3.10` does not define**:

| Tax | `l10n_ec_code_ats` | `l10n_ec_code_base` | Problem |
| --- | --- | --- | --- |
| `income_tax_withholding_302` (*22% 302 WTH*) | `352` | `302` | The record is named after, and declares, concept `302`; the ATS code reads `352`, which no `Tabla 3.10` row states. |
| `tax_ice_plastic_bag`, `tax_ice_reduced_plastic_bag` | `3680` | — | An ICE code on an ICE tax. `3680` is not an income-withholding concept, and neither tax is a withholding at all. |

The collector reports both and refuses the row rather than resolving a rate for
them, because there is nothing to resolve: inventing one would put a fabricated
percentage in a filed return. `352` looks like a transposition of `302`, and the
record's own name and `l10n_ec_code_base` both say so — but the correction
belongs to the `l10n_ec` chart template, upstream in Odoo core, not to this
addon, so it is recorded here rather than worked around.

### The `1900-01-01` sentinel

`l10n.ec.temporal` makes `date_start` required. Five in-scope tables carry no
date in the source at all: the referred transaction types and the month codes
have no date column, `Tabla 14` and `Tabla 15` have none either, and `Tabla 4`
spells `vacío` in all forty rows of its `Fecha de vigencia` column. Their
entries therefore carry `1900-01-01` as a sentinel that means *"the source
states no date"*, with `date_end` empty.

`1900-01-01` was chosen over a plausible-looking date such as `2000-01-01`
(the earliest `Fecha Inicio` the workbook itself uses elsewhere) precisely
because a sentinel must not be mistakable for real data. A decision to change
it belongs in the mixin's field help, which is where a reader looks first.

### `Tabla 4` validity dates live in prose footnotes

The `Fecha de vigencia` column is empty for every row, yet rows `B91` and
`B92` state in prose that code `364` is in force from `01/04/2017` and that
code `375` was in force from `01/12/2020` to `31/12/2021`. Those dates were
**not** imported. Encoding two of forty rows while the other thirty-eight
keep the sentinel would make the two sets overlap, and giving the rest a
start date early enough to avoid that would be inventing thirty-eight values
to keep two real ones. Until the SRI publishes the column, the whole table
reads as undated. Worth a maintainer's view.

### `Tabla 2` rows that name no transaction type

`Tabla 2` states, per row, which transaction type of the referred tables
applies. Six of the seven names it uses appear there verbatim; two do not:

- `C37:C39` read `FONDOS Y FIDEICOMISOS`, while the referred tables `B13`
  reads `Fondos y Financiero`. Same concept family, different words, and the
  workbook offers no other link.
- `C40` reads `COMPROBANTES ANULADOS`, which the referred tables does not
  carry at all.

`transaction_type_codes` is left empty for codes `15`, `16`, `17` and `18`
rather than guessed. The generation preflight is what reports them: an
unresolvable lookup must raise, not invent.

### The SRI contradicts itself on `Tabla 4` ↔ `Tabla 5`

`Tabla 4` column F says document `375` (liquidación de compra RISE) is
supported by sustentos `01` through `08`. None of `Tabla 5`'s rows `D97` to
`D104` names `375` back. Every other pair in the two tables is reciprocal.
Both sides are stored as the source states them and the gap is asserted in the
test suite, so a future release that closes it changes the assertion rather
than passing unnoticed.

### `Tabla 12` has no code column

The sheet identifies a VAT regime by its percentage only. The entry `code` is
therefore that percentage rendered as two digits (`12`, `14`) and `percentage`
is the source fraction multiplied by 100, because the ATS field is a whole
percent. This is the only table whose `code` repeats across rows.

### Two source spellings left verbatim

`Tabla 12`'s title reads `PROCENTAJE DE IVA` — `PROCENTAJE`, not
`PORCENTAJE`. The `name` field reproduces it rather than correcting it,
because a catalog value nobody can trace to a cell is a value nobody can
trust. Correcting a typo is a maintainer's call, not an importer's.

Separately, `Tabla 4` gives codes `373` and `374` the same description,
`Nota de  débito  operadora transporte / socio`, with different
`Código Secuenciales Transacción` values. The catalog keeps both rows
distinct and keeps the duplicate description.

## Deferred work

Effective-dated taxes on `account.tax` itself — `l10n_ec_date_start` /
`l10n_ec_date_end` plus `_l10n_ec_tax_for_date()` and a coverage report — are
a separate proposal in `l10n_ec_base`, not in ATS v1. ATS reads the rate from
the invoice line's own tax, so v1 is functionally independent of it.
