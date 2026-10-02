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
