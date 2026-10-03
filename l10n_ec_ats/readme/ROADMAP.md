# Roadmap

Two tables live here: what is **not** in the catalog yet, and why, and the
open questions a maintainer has to decide.

## Out of scope in v1, with rationale and a v2 proposal

Each entry states the evidence and what a future version would need. The table
below is reproduced **verbatim** from the feature document's §4.2; the paragraphs
around it are this module's own.

| Block | Why out of v1 | Evidence | v2 proposal |
|---|---|---|---|
| **Rendimientos financieros (IFI's)** | Financial institutions under Superintendencia de Bancos / Economía Popular. **Excluded by explicit project decision — permanently, not deferred.** | ficha §1 bullets 5 & 8; `ats.xsd:632` `rendFinancieros` | None. Never implemented. |
| **Recap** (card issuers) | `Tipo 2` contributor. Needs issuer-side card data (affiliated establishment, voucher, commission, consumption split) that has no Odoo representation. | ficha §2.6; `Tabla 2` codes 10/11; `CLAVE PRIMARIA` row 123 | `l10n.ec.card.issuer` + `l10n.ec.card.transaction` + affiliated-establishment model. Large; only for card issuers. |
| **Fideicomisos / fondos** | Needs trustee administration (beneficiaries, yields, patrimony, distributions) absent from Odoo. | ficha §2.7; `Tabla 9` (23 trust types) | `l10n.ec.trust` + `l10n.ec.trust.beneficiary`. Only for `administradoras`. |
| **Exportaciones / ingresos del exterior** | Needs FUE/DAU, distrito aduanero (`Tabla 6`), regímenes aduaneros (`Tabla 7.1`), FOB, refrendo. **No Odoo source** and no SRI EDI document for FUE. | ficha §2.4; `Tablas 6, 7.1, 10, 18, 19` | `l10n.ec.export.document` (FUE) + export fields on `account.move`. **Highest compliance risk of the four** — see §4.3. |
| **Java plugin / DIMM webservice** | Out of scope per project decision. **Local `ats.xsd` validation IS in scope** and reuses the mechanism already in `l10n_ec_account_edi`. | `ats.plugin.1.19.0.zip` (Eclipse/OSGi, `ec.gob.sri.dimm.ats.*`, DIMM 1.19.0) | ADR `readme/adr/0001-ats-java-plugin-and-webservice.md`. When unblocked: a validation-only web service behind a validator interface, so the collection/builder layers stay untouched. |

**One correction to the table above, which is reproduced verbatim and therefore
cannot be edited.** Its last row cites the ADR for the Java plugin decision as
`readme/adr/0001-ats-java-plugin-and-webservice.md`. That ADR now exists, at
[`docs/adr/0001-ats-java-plugin-and-webservice.md`](docs/adr/0001-ats-java-plugin-and-webservice.md)
— under `docs/adr/`, not `readme/adr/`. `oca-gen-addon-readme` renders only
seven known fragments and treats `readme/` as a flat fragment directory, so an
`adr/` subdirectory there would be at best ignored and at worst break the hook.
The decision, the ADR number and the filename are unchanged; only the directory
differs. The design decisions that reverse a filed return are recorded separately
in [ADR 0002](docs/adr/0002-ats-design-decisions.md).

Two of these need to be read carefully, because the obvious summary of them is
wrong:

- **`rendFinancieros` is not deferred.** It is *excluded by explicit project
  decision — permanently, not deferred*, and it is the only row of the five with
  no v2 proposal because there is nothing to propose.
- **`exportaciones` is deferred on a data-model gap, not a policy one.** An
  exporter cannot complete its ATS with v1, which is a real compliance exposure
  for trading companies. The absence is recorded deliberately here rather than
  left to be discovered at filing time.

An **exporter** is therefore the one taxpayer v1 cannot serve. `rendFinancieros`
is a banking institution and was excluded by the financial-institution rule;
`exportaciones` was not, and is out for want of a data model. `DESIGN.md` §7
lists every element that is declared absent from the shipped builder and what
would have to exist before each could be emitted.

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
`l10n_ec_base/data/account_tax_group_data.py`: its 414 concepts do not
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

**What ATS does about it, now that generation exists.** Two independent layers
catch the `000`, and neither trusts the other:

1. the collectors refuse it while assembling a row, so the establishment never
   reaches a payload;
2. ATS-11's `establecimiento.no_000` sweep refuses it anywhere in the payload,
   and `validate_estab_codes` walks the tree by **element** name so it cannot
   fire on `codSustento` or `tipoProv` — two different code spaces where `00` is
   a different question.

The wizard turns either refusal into the same aggregated `UserError`, so a
journal set to `000` produces a message naming the journal and the field rather
than a file. **The gap stays open in `l10n_ec_base` on purpose**: tightening
`_constrains_l10n_ec_entity_emission` is a change to merged code and needs its
own PR against `19.0`. ATS v1 is self-contained either way, which is what §5.4b
asks for.

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

## Documents voided through the SRI's online portal are not implementable today

Ficha técnica §2.5 opens the cancelled block with an exclusion the ATS cannot
honour:

> En esta sección se registrarán los comprobantes anulados en el período
> informado, para los reportes mensuales, todos los comprobantes del mes; para
> los reportes semestrales se reportarán todos los comprobantes del semestre.
> **Excluye a los comprobantes dados de baja a través del portal transaccional
> SRI en línea.**

**Odoo has no field recording that.** A document withdrawn through the portal is
an ordinary `state = 'cancel'` move in Odoo — nothing about the portal is
recorded, nothing about the in-line cancellation is stored, and there is no
portal-side receipt to import. So the collector's selection
(`move_type in ('out_invoice', 'out_refund')`, `state == 'cancel'`,
`posted_before`, `move.date` in the window) **cannot** tell the two apart, and a
portal-voided document will be filed in the `anulados` block, which the SRI will
reject.

This is stated rather than worked around. Two ways to "fix" it were considered
and both are worse than the gap:

- **Guessing from the authorization.** A document that reached the SRI portal was
  authorized, but so is every document that reached the web service, so the field
  discriminates nothing. Reading `l10n_ec_authorization_date` or the access key
  would exclude portal voids only by excluding ordinary cancellations too.
- **Adding a field.** A `Boolean` on `account.move` recording how the document
  was cancelled would be a usable design — and it is a field nothing in the tree
  would ever set, so it would default to the wrong answer for every existing
  document. It is a change to `l10n_ec_base` or to `l10n_ec_account_edi`, both of
  which are merged addons, so it cannot travel in this addon's PR either.

**What a maintainer has to decide.** Whether the ATS should offer the exclusion
at all. If the answer is yes, the honest route is a field written by the user (or
by an SRI-response hook that does not exist yet) plus a migration that cannot be
back-filled — which means a maintainer's view on what a company with a portal
void in its history is supposed to file. Until then the block is **over-inclusive
on this one exclusion** and says so.

## Should cancelled **withholdings** be in the `anulados` block?

Odoo Enterprise's `_get_void_moves` collects two populations and adds both to the
same list:

1. cancelled sales documents, and
2. cancelled **withholdings** — `move_type = 'entry'`, on a withholding journal,
   with `l10n_ec_authorization_number != False`.

**ATS v1 is sales documents only.** That is a scope decision, not an oversight,
and it rests on three pieces of evidence:

- **The ficha does not mention withholdings.** §2.5 says *"los comprobantes
  anulados"* and describes the field as *"el número de autorización que le otorga
  el SRI **para la impresión de sus comprobantes**"* — a series of sales
  documents. Nothing in the block describes a retention certificate.
- **`Tabla 4` code `18` is scoped away from them.** Its description is
  *"Documentos autorizados utilizados en ventas **excepto N/C N/D**"*, and a
  withholding certificate is neither a sales document nor a credit or debit
  note. The nearest real code is `7`, *Comprobante de Retención*, whose
  *Código Secuencial Transacción* column reads `ninguno` — it cannot be reached
  from this block either.
- **A retention has no `establecimiento`/`puntoEmision` series to cancel.** The
  whole block is built on the printed-series triple. `l10n_ec_withhold` gives a
  withholding a number, but nothing establishes it as a point in an issuable
  series the way an invoice journal does.

**Enterprise's treatment is the reference for a future version**, quoted rather
than copied: `move_type = 'entry'` on a withholding journal with a non-empty
`l10n_ec_authorization_number`, added to the same void list. If v2 includes them,
that is the reference implementation — and it will need the same decision this
block had to make about `tipoComprobante`, plus a source for the triple.

## The `journal` key is not on every error of every block

ATS-08's docstring on `collect_ventas_establecimiento_with_errors` states:

> Every key is present on every error from every block, so a consumer can read
> either without a `KeyError`.

That is true of the errors **ATS-08 wrote** — `_l10n_ec_add_establishment`,
`_l10n_ec_ventas_estab_row` and `collect_iva_header_with_errors` all carry
`journal`. It is **not** true of the two blocks before it, and the claim as
written overstates the state of the model. The dicts built by
`_l10n_ec_compras_row`'s and `_l10n_ec_ventas_row`'s `report` closures, and by
every helper that appends directly — `_l10n_ec_reported_date`,
`_l10n_ec_iva_withholdings`, `_l10n_ec_formas_de_pago` — carry
`{"move", "field", "message"}` and **no** `journal`.

The `anulados` block honours the contract in full, so from here on new errors do;
retrofitting the two older blocks is left out because it is a change to shipped,
reviewed code with no behaviour gain beyond a `KeyError` that a consumer has not
hit yet.

**A maintainer has to pick one**: either retrofit the two older blocks and keep
the contract as documented, or amend the ATS-08 docstring to say the contract
applies from ATS-08 onwards. Both are fine; having the code and the docstring
disagree is not.

## Deferred work

### Effective-dated taxes on `account.tax` — a separate proposal in `l10n_ec_base`

The proposal below is reproduced **verbatim** from the feature document's §5.7.

The rate-history problem is **wider than ATS**. `account.tax` has no temporal model, so reports 103, 104, 103/104 aggregations and ATS all read the current rate regardless of the document's date. The correct fix is localization-wide:

- `l10n_ec_base`: `account.tax` gains `l10n_ec_date_start` / `l10n_ec_date_end` (localized names, shadowing nothing) plus `_l10n_ec_tax_for_date(date)`, and a constraint preventing overlapping windows within `(company_id, l10n_ec_code_ats)`.
- A coverage report — the same idea as §5.6 Level 3 — listing, per period, which codes lack full coverage. This is the "control de que los datos están completos" the user asked for, applied to taxes rather than catalogs.
- A migration from the current duplicate-record-plus-`active` pattern.

**Why it is out of ATS v1 scope.** ATS reads the rate **from the invoice line's own tax**, not from the tax's validity window, so v1 is functionally independent. It also modifies a core model, which is a materially different review risk than a new addon and belongs in its own PR against `l10n_ec_base` (companion to PR #104). Recorded in `readme/ROADMAP.md`.

What it means for this addon, stated plainly: **nothing changes here, and that
is the reason it is not here.** ATS reads the rate from the invoice line's own
tax (`_l10n_ec_taxed_amount` →
`move._prepare_edi_tax_details`), never from a validity window, so the ATS
generator is functionally independent of the proposal. What the proposal fixes is
reports 103 and 104 and the 103/104 aggregation, which *do* read the current
rate regardless of the document's date — a defect in those, not in this.

ATS v1 does already own the mechanism the proposal would extend: the
`l10n.ec.temporal` mixin, `_applicable_on()`, and the preflight that turns a
coverage hole into a named refusal. When the proposal is taken up, the catalog
side of the work is done.

## The wizard has a form view and a menu entry, and it reports warnings

Resolved. `views/l10n_ec_ats_generate_views.xml` carries the form, the action and
a menuitem under `l10n_ec.sri_menu`, the same root `l10n_ec_account_edi` hangs
its documents off, so the feature is where somebody filing to the SRI already
looks.

The warnings came with it. `_l10n_ec_run()` returns `(attachment, violations)`
for exactly that reason, and `generate()` was discarding the second element — an
*alerta* was computed and then dropped, which is indistinguishable from the check
never having run. `generate()` now writes them to the wizard's `warnings` field
and the form renders it. The file still downloads; a finding never blocks a
return the SRI accepts.

**Odoo 19 has no non-raising user-facing exception, which is why a field and not
a `Warning`.** `odoo.exceptions` carries no `Warning` and no `Notification` — the
only warning-shaped class in it is `RedirectWarning`, and that is for redirecting,
not for reporting. `from odoo.exceptions import Warning` is precisely what the
mandatory `odoo-exception-warning` check exists to refuse. The
`{"warning": {"title", "message", "type"}}` dict is real, but it is the
**onchange** contract: `odoo.orm.models._onchange_eval` reads it, and
`addons/web/models/models.py` formats it in `onchange()`. Nothing in the action
path consumes it on a button's return value. A stored field on the transient
wizard is the channel that survives to a real user in this version.

## `validators.validate_ats` and `builder.build_ats_xml` read the header under one key

Resolved. The two layers disagreed — the builder from `payload["header"]`, the
validator from `payload["iva"]` — and the consequences were worse than a
collision. The wizard papered over it with
`L10nEcAtsGenerate._l10n_ec_validation_payload`, a second view of the same dict
carrying both keys. But the *validator* was the only caller that ever got the
alias, so on the real pipeline the header arrived **empty** on the validator side
and every rule in `validate_header` — `IdInformante`'s RUC check digit among them
— evaluated against nothing and reported nothing. A direct call to the validator
passed its tests precisely because the test built the payload in the shape the
validator wanted.

`builder.ats_header(payload)` is now the single place the key is decided, and both
`build_ats_xml` and `validate_ats` go through it. There is no alias left in the
wizard, and a mismatch between the two layers is no longer expressible.

`ATS_HEADER_KEY` is `"header"` and **not** the root element name `iva`, which is
the temptation that caused this: `iva` names the element the header is rendered
*into*, `header` names where the mapping sits in a payload. Same word, different
thing.

## A `ventas` row with no client-side IVA withholding

Resolved the other way from what ATS-11 shipped, and it is a behaviour change.

`ESQUEMA` row 24 reads: *"Debe ser igual a la baseImpGrav aplicando el
porcentajeIva (tabla 11). **El valor puede ser mayor o igual**, si no existe
valor colocar 0.00"*. ATS-11 read *"puede ser mayor o igual"* as a **floor** on
the lowest `Tabla 11` share in force, so `valorRetIva = 0.00` against a non-zero
`baseImpGrav` was a `SEVERITY_ERROR`.

**That reading is not shippable.** The cell sanctions `0.00` explicitly — *"si no
existe valor colocar 0.00"* is what to file when there is no withholding — so a
floor makes the cell's own sanctioned value an error and the two clauses cannot
both hold. And the floor refuses every sale whose client withheld nothing, which
is most sales, so a company could not file a sales period at all.

What replaced it: `0.00` produces no finding; a value equal to `baseImpGrav` times
one `Tabla 11` share **in force for the reported period** is clean; anything else
is the existing `SEVERITY_WARNING`. **There is no grave branch left on this
field.** *"Puede ser mayor o igual"* is now read for what it is for —
over-withholding is tolerated — and the `air` block already reads its own
`valRetAir` this way, exempting `0.00` instead of reconciling it against
`porcentajeAir`.

The shares are still resolved through the catalog for the period, so the
comparison is never against a literal.

## Two `Tabla 3.10` groupings the SRI does not state

`detail_group` is loaded for eight codes from the ficha técnica's prose. Two
things about it are worth a maintainer's eye:

- **The ficha's list is timeless and the codes are not.** It names `330`, `341`
  and `342` as dividend/banana concepts; all three were dropped by the SRI from
  2020 and are in no group for a current period. The grouping follows the eras,
  which is right, but it means the ficha's list cannot be read as "these eight
  codes always need a sub-report".
- **The selection rule is the era's own description.** An era is grouped only
  when the sheet's description for *that era* names dividends or `banano`, which
  is checkable against a cell and leaves eighteen eras ungrouped. A different
  reading of the ficha would group a different set, and nothing in the source
  chooses between them.
