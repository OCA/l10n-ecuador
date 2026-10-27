# Design

The spec lives in three artifacts, all shipped under `docs/reference/`
so a reviewer reads exactly what the collector was built against:

- `FORMULARIO IVA.xlsx`, sheet `1 Disenio` — every box number and the
  only stated formulas in the whole project (699 = 620+621, 799 = sum of
  withholdings, 801 = 799−800−802, 859 = 699+801).
- `Guía para el llenado del Formulario Impuesto al Valor Agregado
  IVA.PDF` — prose definitions (484 minimum rule, 563 formula, 601/602
  exclusivity, 609, 615).
- The EC chart template (`odoo/addons/l10n_ec`, outside this repo) — the
  real box→tax mapping through the repartition-line tags.

One row per 104 box, mapping it to the record it is read from, the method
that reads it, and the rule that fills it. It exists so a reviewer can check
the work without reading the collector line by line.

## How to read this document

| Column | What it points at |
| --- | --- |
| **Box** | The SRI box number in `FORMULARIO IVA.xlsx`, sheet `1 Disenio`. |
| **Source of truth in Odoo** | The record the value is read from, or **manual** when the box is cross-period or case-file state the moves cannot supply. |
| **Collector method** | `models/l10n_ec_104_collector.py` unless stated. |
| **Tag / derivation** | The `Reporte 104` tag read off the posted lines, or the computation for boxes the chart carries no tag for. |
| **Rule** | The SRI guide paragraph or the derived rule (D1–D7, see §4) the box follows. |

Two abbreviations recur. **«tag»** means a `Reporte 104` tag on the tax
repartition lines of the EC chart template, reaching the posted lines as
`account.move.line.tax_tag_ids` (Odoo 19 renamed the field; `tag_ids` does
not exist on the move line). **«computed»** means the collector derives the
box because no tax carries its tag -- verified by scanning every repartition
line of `odoo/addons/l10n_ec/data/template/account.tax-ec.csv`.

Sign convention, shared by all three blocks: the collector negates every
tagged sales balance (`-balance`, mirroring core's `-401 (Reporte 104)`
formulas: invoice credits count positive, credit-note debits count
negative) and adds every tagged purchase balance (`+balance`, mirroring
core's `500 (Reporte 104)` formulas: bills count positive, notes count
negative). Net boxes therefore come out as gross minus notes with no
special case.

---

## 1. Ventas (`_l10n_ec_104_collect_ventas`)

| Box | Source of truth in Odoo | Collector method | Tag / derivation | Rule |
| --- | --- | --- | --- | --- |
| 401, 402 | base lines of posted `out_invoice` | tag loop | 401 / 402 base-invoice tags | gross nonzero sales; 402 = fixed assets (the tax, e.g. `tax_vat_15_412`, selects it) |
| 403, 404 | same | tag loop | 403 / 404 base-invoice tags | 0% without credit right (art. 55-56 LRTI) |
| 405, 406 | same | tag loop | 405 / 406 base-invoice tags | 0% with credit right |
| 407, 408 | same | tag loop | 407 / 408 base-invoice tags | exports of goods / services |
| 410, 420, 430 | — no chart tax publishes them | initialized 0.0 | «computed» (absent input) | variable tourism rate; stays 0.0 until the chart ships the taxes |
| 425, 435, 445 | base/tax lines of posted sales | tag loop | 425 / 435 base, 445 tax | 5% construction materials (2024 law) |
| 411–418 | base lines of posted `out_invoice` + `out_refund` | tag loop | 411…418 base tags (refund side carries net tags only) | net = gross − notes, by tag design |
| 421, 422 | tax lines of posted sales moves | tag loop | 421 / 422 tax tags | generated tax |
| 423, 424 | `out_refund` linked via `reversed_entry_id`, paired by account+product | `_l10n_ec_104_rate_adjustment` | «computed» | D5 |
| 431, 441 | base lines | tag loop | 431 / 441 tags | non-object / exempt (informative in v1) |
| 434, 444, 454 | base/tax lines | tag loop | 434 / 444 / 454 tags | reimbursements as intermediary (informative) |
| 442, 443 | base lines of posted notes | tag loop | 442 / 443 tags | notes to offset next month |
| 453 | **manual** | initialized 0.0 | no tag in the chart | carryover, portal-side |
| 409, 419, 429 | the buckets above | sums | «computed» | D1, D3 |

## 2. Compras (`_l10n_ec_104_collect_compras`)

Mirror of §1 with purchase signs.

| Box | Source of truth in Odoo | Collector method | Tag / derivation | Rule |
| --- | --- | --- | --- | --- |
| 500, 501 | base lines of posted `in_invoice` | tag loop | 500 / 501 base-invoice tags | with credit (501 = fixed assets) |
| 502 | same | tag loop | 502 base-invoice tags | without credit right |
| 503, 504, 505 | same | tag loop | 503 / 504 / 505 base-invoice tags | service imports / goods imports / fixed-asset imports |
| 506, 507, 508 | same | tag loop | 506 / 507 / 508 base-invoice tags | 0% imports / 0% local / RISE-popular businesses |
| 530, 533, 534 | — no chart tax publishes them | initialized 0.0 | «computed» (absent input) | variable-rate purchases; 0.0 until the chart ships them |
| 540, 550, 560 | base/tax lines | tag loop | 540 / 550 base, 560 tax | 5% materials with credit |
| 510–518 | base lines of posted `in_invoice` + `in_refund` | tag loop | 510…518 base tags (refund side net only) | net = gross − notes, by tag design |
| 520–525 | tax lines of posted purchase moves | tag loop | 520…525 tax tags | creditable VAT paid |
| 526, 527 | `in_refund` linked via `reversed_entry_id`, paired by account+product | `_l10n_ec_104_rate_adjustment` | «computed» | D5 mirror |
| 531, 541, 532, 542 | base lines | tag loop | 531 / 541 / 532 / 542 tags | non-object / exempt (informative in v1) |
| 535, 545, 555 | base/tax lines | tag loop | 535 / 545 / 555 tags | reimbursements (informative) |
| 543, 544, 554 | base/tax lines or **manual** | tag loop + 0.0 | 543 / 544 / 554 tags where published | notes to offset next month |
| 509, 519, 529 | the buckets above | sums | «computed» | D1 mirror, D3 mirror |

## 3. Liquidación (`_l10n_ec_104_collect_liquidacion`)

| Box | Source of truth in Odoo | Collector method | Tag / derivation | Rule |
| --- | --- | --- | --- | --- |
| 480, 481 | posted `out_invoice` nonzero bases (401/402/410/425), split by payment term | `_l10n_ec_104_cash_credit_split` | «computed» | cash = no term or single zero-day line; else credit (art. 67 LRTI, 159 RALRTI) |
| 482 | ventas block | carry 429 | «computed» | layout: «trasládese campo 429» |
| 483 | **manual** (`carryover_483`) | carryover, default 0.0 | prior 485 | guide: register prior 485 |
| 484 | cash VAT of 480 (421/422/430/445 on cash invoices) | `_l10n_ec_104_cash_credit_split` | «computed» | D4 |
| 485 | 482 − 484 | subtraction | «computed» | guide: difference 482−484, carried to next 483 |
| 486, 487 | **manual** | initialized 0.0 | credit-month / COPCI size | art. 159 RALRTI / COPCI art. 53 |
| 499 | 483 + 484 | addition | «computed» | layout: 483+484 |
| 563 | ventas boxes | (411+412+420+415+416+417+418)/419 | «computed» | D2 |
| 564 | compras boxes × 563 | (520+521+534+560+523+524+525+526−527) × 563 | «computed» | 522 excluded (no credit right); arts. 66 LRTI, 153/157 RALRTI |
| 565 | credit base − 564 | subtraction | «computed» | guide: factor credit vs VAT paid |
| 601, 602 | 499 vs 564 | mutually exclusive max | «computed» | guide: a value in one forbids the other |
| 609 | posted sales lines carrying the 609 tag | `_l10n_ec_104_tagged_sales_lines` | 609 tag | 0.0 until the withhold flow records them (D6) |
| 603, 604, 607, 608, 610–614 | **manual** (`carryover_*`) | carryover, default 0.0 | offsets/adjustments | case-file state, portal-side |
| 605, 606 | **manual** (`carryover_*`) | carryover, default 0.0 | prior credit balances | must be ≤ prior 615/617 (portal checks) |
| 615, 617, 618, 619 | **manual** | initialized 0.0 | next-month balances | cross-period accumulation, out of v1 |
| 620 | 601−602−carryovers−609+carryovers | literal formula | «computed» | layout order preserved |
| 621 | **manual** (`carryover_621`) | carryover, default 0.0 | presumptive/miscellaneous | pre-2013 / post-2021 special cases |
| 699 | 620 + 621 | addition | «computed» | layout: 620+621 |
| 721–731 | posted purchase lines carrying the tags | `_l10n_ec_104_tagged_purchase_lines` | 721…731 tags | 0.0 until the withhold flow records them (D6) |
| 799 | sum of 721…731 | addition | «computed» | layout: 721+723+725+727+729+731 |
| 800, 802 | **manual** (`carryover_*`) | carryover, default 0.0 | provisional offset / public unpaid | case-file state |
| 801 | 799 − 800 − 802 | subtraction | «computed» | layout: (799−800−802) |
| 859 | 699 + 801 | addition | «computed» | layout: (699+801) |

## 4. Derived rules a reviewer should challenge

These are the project's own readings where the sources do not state a
formula. Each names its evidence and what would prove it wrong.

- **D1 — 409/419 include the 5% boxes (425/435); 509/519 include 540/550.**
  Evidence: positional -- the 5% rows sit inside their sections (xlsx rows
  12 and 44) before the TOTAL rows (21 and 55); a section total covers its
  section. Proven wrong by: an SRI calculation sheet excluding them.
- **D2 — 563 follows the guide formula literally, 435 excluded from the
  numerator; 1.0 when 419 is zero.** Evidence: the guide prints
  (411+412+420+415+416+417+418)/419 verbatim; 419 = 0 leaves 0/0, and with
  no sales to apportion there is nothing to penalize, so the suggested
  factor keeps the full credit (editable in the portal, as the SRI marks
  it). Proven wrong by: a portal default for empty months.
- **D3 — 429 = 421+422+423−424+430+445 (529 mirrored).** Evidence: 429 is
  the section's generated-tax total; 424 (in favor) is the only component
  with a favor sense, so it subtracts. Proven wrong by: an SRI
  calculation sheet composing it otherwise.
- **D4 — 484 defaults to the cash VAT.** Evidence: the guide asks for *at
  least* the VAT of 480, *plus* the credit VAT *as applicable* --
  unknowable from the moves (collection timing), so the prefill books the
  knowable minimum and carries the rest to 485. Proven wrong by: a rule
  settling credit VAT by default.
- **D5 — 423 only with variable boxes present, else 424; 526/527 mirror
  (lower→526, higher→527).** Evidence: the guide gates 423 on the
  reduced-rate taxpayer (410/420) and books absolute differences; the
  purchase pair has no such gate. Proven wrong by: a 423 filed without
  variable rates, or a 526/527 split on other grounds.
- **D6 — 609 and 721–731 read tags (0.0 without the withhold flow).**
  Evidence: the chart publishes the tags on the withhold taxes
  (`tax_sale_withhold_vat_100` → 609); the withhold documents recording
  them belong to `l10n_ec_withhold` (separate PR). Proven wrong by: a
  v1-scope source recording customer withholdings.
- **D7 — every carryover defaults to 0.0 and stays user input.**
  Evidence: 483/605–608/615–619 reference prior filings no query in this
  addon can reach. The wizard surfaces them as named fields rather than
  hiding them. Proven wrong by: a prior-filing store this module should
  read (a stated v2 glue, not v1 scope).
