# ADR 0001 — ATS design decisions that are not obvious from the code

- **Status:** accepted
- **Date:** 2026-10-03
- **Scope:** `l10n_ec_ats` (Tipo 1 ATS generation)
- **Sources:** `Catalogo_ATS.xls` (`ESQUEMA TIPO 1 Y 2`, `CLAVE PRIMARIA (2)`,
  `TABLAS REFERENCIALES`), _Ficha Técnica Transaccional Simplificado ATS_,
  `data/xsd/ats.xsd`, and Odoo Enterprise's `l10n_ec_reports_ats` as a **reference
  only** (see the last section).

## The bar for what belongs here

A decision is recorded in this ADR if and only if **reversing it would silently produce
a wrong filed return** — a file that passes `ats.xsd`, passes this module's own
validators, and is nonetheless not what the SRI asked for. That is a high bar on
purpose. Naming conventions, model structure and anything a test already pins do not
belong; they are visible in the code and the suite.

Each entry below states the decision, the **evidence** that settles it, the
**alternatives considered**, and the consequence a future maintainer inherits.

---

## 1. The `ESQUEMA` column versus the ficha prose: the numbered prose governs

**Decision.** `Catalogo_ATS.xls` / `ESQUEMA TIPO 1 Y 2` column `J` (`Validaciones`) is
authoritative **where the ficha técnica is silent**. Where the two conflict, **the
ficha's numbered prose governs**.

**Evidence.** The column is a summary of the DIMM desktop tool's input screen; the ficha
is the filing specification, organised per field. Two cells contradict it, and in both
the prose is the sentence written about a case the specification itself requires to be
expressible:

| Cell            | The `Validaciones` column says                                                                                                                                              | The ficha says                                                                                                                                                                                                                      |
| --------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `secuencialFin` | _"debe ser mayor a secuencialInicio"_                                                                                                                                       | §2.5: _"Para anular un solo comprobante, se debe indicar este número en ambos campos."_                                                                                                                                             |
| `totalVentas`   | _"Casillero no editable, debe ser igual a la sumatoria de los valores registrados en los campos baseNoGraIva, Base Imponible y baseimpGrav. **Solo Facturación Física F**"_ | §2.1 defines the field as _"el total de las ventas realizadas en el período informado (valor consolidado de todos los establecimientos del contribuyente)"_ with no emission-type restriction; §2.3 then bounds `ventasEstab` by it |

**Alternatives considered.**

- _The column always governs._ It makes cancelling a single document unrepresentable
  (§5.4 below) and makes the two `totalVentas` cells mutually unsatisfiable.
- _Enterprise's behaviour as evidence._ Enterprise's `ent_ats` reproduces the
  spreadsheet's reading and filters `tipoEmision == 'F'` in **both** accumulations,
  which makes the ficha's own ceiling vacuous. Enterprise is a reference, not a
  specification (§12).
- _Ask the SRI._ Correct in principle, not available to an open-source addon.

**Consequence.** Every rule in `validators.py` that touches one of these cells cites the
prose, not the column, and `ROADMAP.md` carries the third contradiction — the
`totalVentas` "Solo Facturación Física F" clause, which three readings explain and **no
source chooses between**. That one is still open, and it is the only place this
precedence rule could turn out to be wrong.

**Where it lives:** `validators.py:34-62` (module docstring).

---

## 2. `totalVentas` is gross; `ventasEstab` is net

**Decision.** `totalVentas` = Σ of `baseNoGraIva` + `baseImponible` + `baseImpGrav` over
the **`ventas` rows**, gross. `ventasEstab` = the **net** sum over one establishment's
documents, with `out_refund` subtracting. The two are therefore **deliberately
unequal**, and `ventasEstab` may be negative.

**Evidence.** Three independent sources agree.

1. `ESQUEMA` row 103 defines the block figure as _"el valor **neto** (se restan los
   valores de NC) de todas las ventas registradas, **caso contrario error**"_.
2. `ats.xsd` types `ventasEstab` as `totalVentasType` (`data/xsd/ats.xsd:1500`) — the
   **only** amount type in the schema whose pattern admits a leading minus, and the SRI
   gave it to no other element inside Tipo 1. Every `ventas` base is `monedaType`,
   `minInclusive 0.0`.
3. The ficha's ceiling — _"la sumatoria del total de ventas por los establecimientos
   **no puede ser mayor** al valor registrado en el campo total ventas"_ (§2.3) — is
   only informative if a row can come out _below_ `totalVentas`. Under the gross reading
   of both figures it would be an equality, and the word _may not exceed_ would say
   nothing.

**Alternatives considered.**

- _Make them equal_ — i.e. subtract credit notes from `totalVentas` too. Then a credit
  note is counted twice negatively and the ficha's ceiling is unfalsifiable. Rejected:
  the ceiling is the only sentence that tells us which figure is which.
- _Clamp `ventasEstab` at `0.00`._ A company that credited more than it invoiced from
  one establishment has a genuinely negative net figure. Clamping states a number the
  company never had.
- _Take `monedaType` at its word and refuse the negative._ Then the schema's one signed
  type is unexplained and a legitimate filing is unfileable.

**Consequence.** The validator enforces the inequality (`ventas_estab.tope`,
`validators.py:929`) rather than an equality, and `totalVentas` is read out of the
`ventas` rows and **never re-aggregated** from the documents (`_l10n_ec_total_ventas`,
collector `:2138`). The collector signature
`collect_iva_header(ventas_rows, ventas_establecimiento_rows)` makes both blocks
**required arguments**, so a caller cannot obtain one header field without the block
that defines it, and cannot wire them to different periods.

---

## 3. `secuencialFin` equals `secuencialInicio` for a single-document cancellation

**Decision.** A run of one cancelled document emits the same sequential in both
`secuencialInicio` and `secuencialFin`.

**Evidence.** `ESQUEMA` row 211 says _"debe ser mayor a secuencialInicio"_. Ficha
técnica §2.5 says _"Para anular un solo comprobante, se debe indicar este número en
ambos campos."_ The prose is the sentence written about **this exact case**; the column
is a summary of a desktop form.

**Alternatives considered.**

- _A strict `>`._ Cancelling one document becomes **unrepresentable** — not awkward,
  unrepresentable. The SRI's own instruction would have no encoding.
- _Emit no row for a single cancellation_ and let the document go unreported. That is
  the substitution this addon exists to prevent: the SRI would treat an unlisted
  document as not cancelled.
- _Add a dedicated single-cancellation element._ The schema has none.

**Consequence.** `validate_ats` deliberately applies **no** range rule to `anulados`
(`validators.py:1479`): the one cell that would contradict this is the one cell the
collector's run-splitting already encodes. A run of more than one document still emits a
strictly larger `secuencialFin`, because the runs are built from consecutive numbers.

**Where it lives:** `_l10n_ec_anulados_row`, collector `:2609`.

---

## 4. One row per **contiguous run** of cancelled sequentials

**Decision.** The `anulados` group key is
`(establecimiento, puntoEmision, tipoComprobante, autorizacion)`; within a group, a run
breaks wherever the next sequential is not this one **plus one**.

**Evidence.** Two sentences.

1. Ficha §2.5: _"Se debe considerar que se considerarán anulados los comprobantes que
   consten dentro del rango informado."_ **A range is an assertion about every document
   inside it.**
2. `CLAVE PRIMARIA (2)` rows 196–201 mark **all six** elements of `detalleAnuladosType`
   as _componente de clave general_ — including `autorizacion`, which the ficha makes
   obligatory at 3–49 digits on every row.

**Alternatives considered.**

- _One row per `(establecimiento, puntoEmision, tipoComprobante)`, taking `min`/`max`._
  Cancelling 5, 6, 7 and 9 emits `5`–`9`, which tells the SRI that 8 was cancelled too.
  That is a false statement about a live document.
- _`autorizacion` read off the first member of the group._ Permitted by the schema and
  wrong: each document has its own number, so one row could state document A's
  authorization for a set containing B.
- _String comparison for contiguity._ `"9"` does not follow `"8"` as strings when one is
  `000000008`; contiguity is a property of the **value**.

**Consequence, and it is a useful one to state plainly:** because `autorizacion` is part
of the key and every electronically issued document has its own, **in real data every
`anulados` row is a single document with its number repeated in both fields** — exactly
what the ficha prescribes. Ranges are the physical-invoicing case, where one
authorization covered a printed batch (_"el número de autorización que le otorga el SRI
**para la impresión** de sus comprobantes"_). The feature is implemented and general;
the data rarely needs it. Two records claiming one sequential is a data defect, not a
second range: the first is kept, the second is reported.

**Consequence for refusals.** A refused document is removed from the runs **before**
they are built (`collect_anulados_with_errors`, collector `:2209`). A range must be
built only from documents that will actually appear in the file, or a row would span a
document the file never reports — the same false assertion in a subtler form.

---

## 5. `valorRetIva` has no floor, and no grave branch

**Decision.** `0.00` produces **no** finding. A value equal to `baseImpGrav` × one
`Tabla 11` share in force for the reported period is clean. **Anything else is a
`SEVERITY_WARNING`**, and there is no error branch left on the field.

**Evidence.** `ESQUEMA` row 24 reads, in one sentence: _"Debe ser igual a la baseImpGrav
aplicando el porcentajeIva (tabla 11). **El valor puede ser mayor o igual**, si no
existe valor colocar 0.00"_. Read _"puede ser mayor o igual"_ as a **floor** and the
sanctioned `0.00` of _"si no existe valor colocar 0.00"_ becomes an error whenever
`baseImpGrav` is non-zero. The two clauses cannot both hold, so the sentence itself
settles which one yields.

**Alternatives considered.**

- _A floor on the lowest `Tabla 11` share in force._ This was **what ATS-11 shipped**,
  and it is not shippable: it refuses **every sale whose client withheld nothing**,
  which is most sales, so a company could not file a sales period at all — and the
  message would blame the company rather than the rule.
- _A grave finding when the value exceeds every share._ _"Puede ser mayor o igual"_
  exists precisely to permit over-withholding. Blocking it would refuse returns the SRI
  accepts.

**Consequence.** _"Puede ser mayor o igual"_ is read for what it is for:
**over-withholding is tolerated**, not bounded. The shares are still resolved through
the catalog for the period (`resolve_rates`), so the comparison is never against a
literal. The `air` block already reads its own `valRetAir` the same way — exempting
`0.00` instead of reconciling it against `porcentajeAir`. This is a **behaviour change**
from ATS-11's first version and is recorded in `ROADMAP.md`.

**Where it lives:** `validate_ventas_row`, `validators.py:1434`.

---

## 6. Absence versus empty in the builder payload

**Decision.** `minOccurs="0"` means an absent key produces **no element**, never an
empty one; and `ventasEstablecimiento` is the one block where a present but empty list
produces **no element** either.

**Evidence.** Read from the artifact, not chosen.

- `detalleCompras`, `detalleVentas` and `detalleAnulados` are all `minOccurs="0"`
  (`data/xsd/ats.xsd:676`, `:711`, `:735`), so an empty wrapper is the schema-valid way
  to say _"collected, nothing found"_.
- `ventaEst` is **`minOccurs="1"`** (`:1493`), so `<ventasEstablecimiento/>` does
  **not** validate. The only honest representation of zero establishments is no element.

**Alternatives considered.**

- _Always emit the wrapper._ Produces a document the schema refuses, for the one block
  where the row count is tied to a header field.
- _Default a missing optional key to `0.00`._ An empty element asserts a value the
  payload does not carry, and a `0.00` asserts that nothing happened — a claim about a
  fact the collector cannot see.
- _Emit `False` as a string._ Observed on this module's first green run:
  `regimenMicroempresa`'s enumeration is `{SI}`, and `str(True)` produces _"The value
  'True' is not an element of the set {'SI}'"_. A `bool` is now **refused** by name, and
  `False` means omit.

**Consequence.** Three separate refusals exist to make the difference visible rather
than silent: a payload key the spec does not declare is refused (ignoring it is how a
field goes missing from a filed ATS while every test still passes); a mandatory key the
payload omits is refused (_"an absent element is not a zero"_); and an element the
schema declares but the builder will never write is **declared** in the spec and refused
with the reason attached, so the specs can still be compared against `ats.xsd` in full.

**Where it lives:** `_render_row` / `_render_block` / `_header_value`, `builder.py:817`,
`:976`, `:1067`.

---

## 7. The `_applicable_on` domain-loss trap

**Decision.** Every catalog read resolves against the **model** and intersects the
result with the table scope **afterwards**. Never the other way round.

**Evidence.** `l10n.ec.temporal._applicable_on` is `@api.model` and calls `self.search`.
`BaseModel.search` does **not** carry the calling recordset's domain, so
`scoped_recordset._applicable_on(day)` re-searches the **whole model** and returns every
row of every table. The failure is silent and looks like a working lookup: `Tabla 04`'s
115 entries come back as though they were `Tabla 12`, and `Tabla 12` code `12` — which
covers three separate windows — matches all three and aborts a period that is perfectly
covered.

**Alternatives considered.**

- _Intersect before resolving_ (`scoped.search(...)` then `_applicable_on`).\* Preserves
  the table filter and **discards the temporal filter**, returning every era of every
  concept at once. Same class of bug, other direction.
- _A custom `read_group`/`_read` inside the mixin._ Would work, and would move the
  `search` semantics the mixin is built on into this addon's own code. The intersection
  is a two-line ordering rule every call site already has to state anyway.
- _`domain_leaf` or `active_test=False` gymnastics._ None of them address the actual
  cause, which is that `search` is model-level.

**Consequence.** Three call sites carry the rule and say so in their docstrings:
`CatalogReader._in_force` (`validators.py:424`), `_l10n_ec_applicable_entries`
(collector `:300`) and the wizard's `_l10n_ec_air_codes`
(`wizard/l10n_ec_ats_generate.py:261`). A fourth trap sits next to it and is worth
stating because it fails the same way — **the table number is zero-padded** (`01`, `02`,
`05`) while `Tabla 04` and `Tabla 11` store their _entries_ unpadded (`1`, `9`). An
unpadded table number matches nothing, and a lookup that matches nothing resolves to
_absent_ rather than raising.

---

## 8. `000` is refused as an establishment or emission point, in three layers

**Decision.** No establishment or emission-point code may be `000`, in any field, and
the rule is enforced independently by the collector, the builder and the validator.

**Evidence.** The XSD does not come close to enforcing this. `establecimientoType`
(`data/xsd/ats.xsd:65`, upstream `:26-30`) and `ptoEmisionType` (`:75`, upstream
`:36-40`) declare **no bounds at all** — pattern `[0-9]{3}` only. `minExclusive 000`
appears in exactly **two** types: `ventasEstabType` (`:1507`, upstream `:1468`) and
`numEstabRucType` (`:1521`, upstream `:1482`). So on the two carriers that matter most
for `compras` and `anulados`, `establecimiento="000"` and `puntoEmision="000"` both
**validate**. The ficha says `numEstabRuc` must be `> 000`; this generalises it to every
establishment and emission-point code, which is the correct reading of how the SRI
numbers establishments.

_(Line numbers above are the **shipped** `data/xsd/ats.xsd`; the code's own docstrings
cite the upstream artifact, whose normalisation — BOM removal, trailing-whitespace
stripping — shifts them. Both are given so either can be opened.)_

**Alternatives considered.**

- _Trust the schema on `ventasEstab`/`numEstabRuc` and nothing else._ The two types that
  carry the bound are the two blocks nobody is tempted to break; the blocks that break
  are the two the schema leaves unconstrained.
- _Fix it upstream in `l10n_ec_base`._ The one-line tightening of
  `account.journal._constrains_l10n_ec_entity_emission` is proposed in `ROADMAP.md`, and
  `l10n_ec_base` is **merged**, so it cannot travel in this addon's PR. Relying on it
  would make ATS's correctness depend on a change that has not been made.
- _Value-driven sweep_ (any value equal to `"000"`). Would fire on `codSustento` and
  `tipoProv`, which live in two-digit code spaces where `00` is a different question.
  The sweep is therefore **name**-driven, with `establecimientoRecap` excluded
  explicitly: it is `estRecapType`, **two** digits, inside the Tipo 2 block.

**Consequence.** This is the canonical demonstration of why two validation layers exist.
XSD validation passes on a document that must never be filed. Each layer catches what
the other cannot: the collector stops it reaching a payload, the builder's `no_zero`
refuses it with the schema's own permissiveness quoted in the message, and
`validate_estab_codes` walks the whole payload tree by element name so a caller cannot
slip one past.

---

## 9. `detalle_group` is era-scoped data on the **rate**, not on the concept

**Decision.** The `air` sub-report grouping (`dividend` / `banana`) lives on
`l10n.ec.ats.income.withholding.rate.detail_group`, and carries a **group name**, never
a code.

**Evidence.** `Catalogo_ATS.xls` carries **no column** saying which `codRetAir` needs
which sub-report, and it cannot be derived from the concept either: the SRI reuses codes
across eras. `340` is _Otras retenciones aplicables el 1%_ until 2015 and _Impuesto
único a la exportación de banano de producción propia - componente 2_ from 2015-03.
`338` is _Compra local de banano a productor_ in 2016 and something else from 2020. 106
of the 414 codes carry a different description in a different era.

**Alternatives considered.**

- _A timeless `Selection` of codes._ Files a banana sub-report against a 2013 concept
  that was not one, and files none at all for the concept that was.
- _A `Many2many` to the concept._ Would force one timeless answer, which is the thing
  the source does not state — the same reason `description` and `family` live on the
  rate.
- _A code in `detail_group` as well as a name._ The code is `concept_id.code`;
  publishing it twice is one fact stated twice and the two could drift.

**Consequence.** The validator's conditional-emission rule **cannot** be evaluated from
the catalog alone, so `AirConditionalCodes` is a caller-supplied seam — and
`validate_compras_row` **raises** when an `air` row carries one of the five conditional
elements and the seam was not supplied (`validators.py:1084`). A check that cannot be
made must not be allowed to look covered. The wizard closes the seam from `detail_group`
for the reported period.

---

## 10. `codSustento` is captured as `Char(2)` and validated by the catalog

**Decision.** `account.move.l10n_ec_tax_support` and `res.partner.l10n_ec_tax_support`
are `Char(size=2)`, not `Selection`s, and `l10n_ec_ats` — not the field — holds the
authority for the code.

**Evidence.** `TAX_SUPPORT` in `l10n_ec_withhold/models/data.py` is a Python literal
listing only `00`–`13`, so `Tabla 5` codes `14` (in force 2018-01-01) and `15`
(2020-06-01) **could not be recorded on a document at all**. A hardcoded `Selection`
silently caps expressiveness at whatever it lists, which is the exact failure an
effective-dated catalog exists to prevent.

**Alternatives considered.**

- _Extend the literal._ A code list owned by a sibling addon, with no window and no
  validation, that has to be updated whenever the SRI republishes.
- _A `Selection` extended to the current codes._ Caps again at the next republication,
  and the rejection message would list codes from Python — stale the moment the SRI
  publishes a new one.

**Consequence.** The rejection message names the codes the catalog **actually accepts
for the reported period**, read from the records, so the guidance cannot go stale the
way a dropdown does. The line-level `account.move.line.l10n_ec_tax_support` and the
withholding wizard line keep their `Selection`: they are dropdowns, and the wizard
builds its label map from the wizard _line_ field, not from `account.move`.

---

## 11. A refusal is never repaired

**Decision.** At every layer, a value that cannot be sourced from a record is **reported
and the row withheld**, never defaulted, clamped, negated or truncated.

**Evidence.** Three cases show what repair would cost. `monedaType` has
`minInclusive 0.0`, so a credit note reduced to a magnitude is a decision about _which_
magnitude the schema can carry, not an arithmetic convenience. Taking an absolute value
in the builder would file a number for a value the caller handed over **and hide a
collector that regressed**. Truncating a twelve-digit overrun would produce a file
describing a company that does not exist.

**Alternatives considered.**

- _Enterprise's `'9999999999'` for a missing authorization._ Its comment reads _"The
  government software does not allow to report documents without authorization number.
  If is not setted, send 9999999999."_ That is an assumed value in Python, and it is the
  single most-cited divergence between this addon and the Enterprise reference (§12). A
  fabricated authorization in a filed return is worse than a missing file.
- _Collect `codSustento` from the document type._ `Tabla 4` → `Tabla 5` is a
  cross-reference, and both sides are stored, but neither is total: the SRI contradicts
  itself on document `375` (§10 of `ROADMAP.md`). Deriving one side from the other would
  invent a third.

**Consequence.** A group that cannot be completed is withheld **as a whole**, not per
member: a sum over a subset is a figure the company never had. A collector returns
`(rows, errors)` rather than raising, so one unusable document does not hide the other
nineteen, and the wizard aggregates every problem into **one** `UserError` — because
somebody fixing March should not have to run generation twenty times to see twenty
problems.

---

## 12. Enterprise `l10n_ec_reports_ats` is a reference, not a specification

**Decision.** Odoo Enterprise's `l10n_ec_reports_ats` was read and is **not copied**. It
is listed here because the divergences are genuinely useful to the next person, and
because "we consulted Enterprise and disagreed" is only credible if the disagreements
are listed.

**Confirmed by convergence — our design independently reached the same names:**

| Field                  | Enterprise                                  | Ours                      |
| ---------------------- | ------------------------------------------- | ------------------------- |
| document authorization | `account.move.l10n_ec_authorization_number` | same name, same semantics |
| related party          | `res.partner.l10n_ec_related_party`         | same name                 |

**Divergences, with the evidence for each:**

| #   | Enterprise                                                                                                                                           | Ours                                                   | Why                                                                                                                                                                                                                                                                                                                 |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `_get_purchase_values` returns the literal `'9999999999'` when no authorization is set                                                               | refuses the file with a `UserError` naming the bill    | an assumed value (§11)                                                                                                                                                                                                                                                                                              |
| 2   | `numEstabRuc = len(set(sale_journals.mapped('l10n_ec_emission')))` — a count of **emission points** presented as a count of **establishments**       | `l10n_ec_entity` and `l10n_ec_emission` kept distinct  | they are different codes, and conflating them misfiles the header of every multi-point taxpayer                                                                                                                                                                                                                     |
| 3   | `LOCAL_PURCHASE_DOCUMENT_CODES`, `FOREIGN_PURCHASE_DOCUMENT_CODES`, `SALE_DOCUMENT_CODES`, `ATS_SALE_DOCUMENT_TYPE` are module-level Python literals | loaded as records from `data/`                         | a hardcoded code list goes stale on the next republication                                                                                                                                                                                                                                                          |
| 4   | no temporality — a historical ATS uses current codes                                                                                                 | every read resolved through `_applicable_on(reported)` | a 2016 filing must use the 2016 tables                                                                                                                                                                                                                                                                              |
| 5   | `ATS_SALE_DOCUMENT_TYPE = {'01': '18', '02': '18'}` maps every sale type to `Tabla 4` code `18`                                                      | the cancelled document's **own** `Tabla 4` code        | code `18` reads _"Documentos autorizados utilizados en ventas **excepto N/C N/D**"_, and `out_refund` is in scope. It is also a literal in a block Enterprise **never emits** — `grep -c 'secuencialInicio\|detalleAnulados'` over its `tax_report.py` returns `0` — so it records a belief, not an accepted filing |
| 6   | filters `tipoEmision == 'F'` in **both** accumulations                                                                                               | no emission-type filter                                | makes the ficha's own `ventasEstab` ceiling vacuous (§1)                                                                                                                                                                                                                                                            |

**Architectural difference that cannot be closed.** Enterprise hooks ATS into
`account.report` via `account.generic.tax.report.handler`, so ATS is a report variant
with period selection and drill-down. `account_reports` is Enterprise-only and an OCA
addon cannot depend on it, so this addon keeps a `TransientModel` wizard and accepts the
worse ergonomics knowingly.

**What was borrowed.** The two-layer intent — Enterprise's `_generate_ats` already
separates `(values, errors)` per block and surfaces errors with an explicit "ignore
errors" action, which is the same shape as this module's `(rows, errors)` plus preflight
abort. Its `float_repr(float_round(x, 2), 2)` independently confirms the two-decimal
rule.

---

## Deliberately **not** recorded here

- **Model and file layout** — `l10n_ec_ats/wizard/` rather than `models/` is forced by
  the repository's mandatory `pylint_odoo` (`no-wizard-in-models`) and has precedent in
  two sibling addons. Visible, testable, reversible.
- **The generic `l10n.ec.ats.catalog.entry` instead of ten typed models** — a structural
  bet, but reversing it changes no filed value.
- **`Tabla 4`'s two-column ambiguity** for `ventas/tipoComprobante`'s filter. The
  decision taken (assert existence only, record the filter for a maintainer) is in
  `ROADMAP.md`, and it is a **coverage** gap, not a wrong-value one.
- **Whether cancelled withholdings belong in `anulados`.** A scope question with three
  pieces of evidence laid out in `ROADMAP.md`; answering it changes what is filed, so it
  is a maintainer's call rather than a recorded decision.
