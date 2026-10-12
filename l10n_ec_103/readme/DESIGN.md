# Design

One row per 103 box, mapping it to the record it is read from, the method
that reads it, and the rule that fills it. It exists so a reviewer can check
the work without reading the collector line by line.

The spec lives in three artifacts, all shipped under `docs/reference/` in
the follow-up documentation commit so a reviewer reads exactly what the
collector was built against (the layout sheet `FORMULARIO RETENCIONES EN LA
FUENTE.xls`, sheet `Formulario RF desde ago 2026`; the taxpayer guide
`GUIA DEL CONTRIBUYENTE FORMULARIO 103.pdf`; the upload guide `GUIA DEL
CONTRIBUYENTE LLENADO DEL XML Y JSON RETENCIONES EN LA FUENTE.pdf`).

## How to read this document

| Column | What it points at |
| --- | --- |
| **Box** | The SRI box number in the layout sheet. |
| **Source of truth in Odoo** | The record the value is read from, or **manual** when the box is cross-period or case-file state the moves cannot supply. |
| **Collector method** | `models/l10n_ec_103_collector.py` unless stated. |
| **Tag / derivation** | The `Reporte 103` tag read off the posted lines, or the computation for boxes the chart carries no tag for. |
| **Rule** | The guide paragraph or the derived rule (D1–D5, see §4) the box follows. |

Two abbreviations recur. **«tag»** means a `Reporte 103` tag on the tax
repartition lines of the EC chart template, reaching the posted lines as
`account.move.line.tax_tag_ids`. **«computed»** means the collector derives
the box because no tax carries its tag -- verified by scanning every
repartition line of `odoo/addons/l10n_ec/data/template/account.tax-ec.csv`.

Sign convention: base (product) lines add while tax lines negate, because
withholding taxes carry negative rates and post with the opposite sign of
the base lines. Vendor bills count positive, vendor credit notes count
negative on both legs, and the net boxes come out with no special case.
Core reads every box with positive formulas (`303 (Reporte 103)`), which
is the same convention.

Vouchers are `entry` moves and are read like any other move: their
counterpart lines ship tag-stripped by the withhold flow, so each event
counts once -- provided the same withholding is not recorded both on the
bill and on a voucher for it.

---

## 1. Residentes (`_l10n_ec_103_collect_residentes`)

Boxes starting with 3 only; the 4xx boxes live in §2.

| Box | Source of truth in Odoo | Collector method | Tag / derivation | Rule |
| --- | --- | --- | --- | --- |
| 302, 352 | **manual** | initialized 0.0 | payroll, no move source | HR out of scope |
| 303–312 (bases) | base lines of posted `in_invoice` | tag loop | 303…312 base-invoice tags | concept rate per chart (e.g. 303 = 10%) |
| 353–362 (valores) | tax lines of posted moves | tag loop | 353…362 tax tags | withheld = −(tax-line balance) |
| 3030–3440 (4-digit concepts) | base/tax lines | tag loop | 4-digit tags (3030, 3120, 3440…) | same rule; rate read from the tax, never assumed (3440 = 2.75%) |
| 314–350 (bases) | base lines | tag loop | 314…350 base tags | royalties, leases, dividends, lotteries, self-withholdings |
| 364–400 (valores) | tax lines | tag loop | 364…400 tax tags | same split rule |
| 332 (no retención) | base lines | tag loop | 332 tag | informative in v1 |
| Refund legs | base/tax lines of posted `in_refund` | tag loop | refund-side tags | mirrored signs, net exact |
| 349, 399 | the legs above | sums over first digit 3 | «computed» | 349 = base legs, 399 = tax legs |

## 2. No residentes (`_l10n_ec_103_collect_exterior`)

Mirror of §1 over the boxes starting with 4. The user classifies by
choosing the concept tax (sustento + box); treaty and haven lists per
payee stay manual in v1.

| Box | Source of truth in Odoo | Collector method | Tag / derivation | Rule |
| --- | --- | --- | --- | --- |
| 402–433 (bases) | base lines of posted `in_invoice` | tag loop | 402…433 base tags (e.g. 410 = technical services, 22%) | per concept |
| 452–482 (valores) | tax lines | tag loop | 452…482 tax tags (e.g. 460) | same split rule |
| 497, 498 | the legs above | sums over first digit 4 | «computed» | 497 = base legs, 498 = tax legs |

## 3. Totales (`_l10n_ec_103_collect_totals`)

| Box | Source of truth in Odoo | Collector method | Tag / derivation | Rule |
| --- | --- | --- | --- | --- |
| 499 | both withheld subtotals | 399 + 498 | «computed» | layout: total retenciones |
| 500 | **manual** (`carryover`) | carryover, default 0.0 | undistributed-profit compensation | only the dividends reading supplies it |
| 501 | 499 − 500 | subtraction | «computed» | layout: total después de compensación |

## 4. Derived rules a reviewer should challenge

- **D1 — base legs add, tax legs negate.** Evidence: withholding taxes
  carry negative rates, so their tax lines post opposite-signed to the
  bases while core formulas stay positive; the refund side mirrors both.
  Proven wrong by: a chart where some valor tag rides a product line.
- **D2 — resident/exterior split by first digit.** Evidence: every
  resident box starts with 3, every non-resident box with 4, in the
  current layout. Proven wrong by: a layout breaking the digit rule
  (then the split becomes an explicit list).
- **D3 — 499 = 399 + 498; base subtotals stay out.** Evidence: 499 is
  the *tax* total; 349/497 are informative. Proven wrong by: an SRI
  calculation sheet composing it otherwise.
- **D4 — 500 defaults to 0.0 as named input.** Evidence: only a
  dividends reading (art. 39.2.1 LRTI) can supply it. Proven wrong by: a
  dividends store this module should read (stated v2, not v1).
- **D5 — v1 pins the ago-2026 layout.** Evidence: 12 layout sheets and
  counting; the version selector is the first ADR, not v1 scope. Proven
  wrong by: a filing period predating the pinned layout.
