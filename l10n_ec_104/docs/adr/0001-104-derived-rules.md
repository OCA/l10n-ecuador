# ADR 0001: derived rules of the Form 104 prefill

Date: 2026-10-12. Status: accepted (v1).

## Context

The SRI layout sheet (`FORMULARIO IVA.xlsx`, `1 Disenio`) numbers every box but states
formulas only for 699/799/801/859/902. The taxpayer guide defines most boxes in prose
(484, 563/564, 601/602, 609, 615) but never the section totals 409/419/429/509/519/529.
The EC chart template tags most boxes and none of the totals or the rate-difference
adjustments. Seven readings below fill those gaps; each is recorded with its evidence
and its falsifier so a later SRI publication can overturn it without redesigning the
module.

## Decisions

1. **Section totals include the 5% boxes** (409 ⊇ 425, 419 ⊇ 435, 509 ⊇ 540, 519 ⊇ 550).
   The 5% rows sit inside their sections before the TOTAL rows. AGambling with exclusion
   would under-report every materials seller.
2. **563 is the guide formula verbatim; 1.0 when 419 = 0.** With no sales there is
   nothing to apportion, so the suggested factor keeps the full credit. The portal marks
   it suggested (editable), which bounds the harm of the default.
3. **429 = 421+422+423−424+430+445 (529 mirrored).** The favor-sense box subtracts;
   everything else adds.
4. **484 defaults to the cash VAT.** The guide's _minimum_ is knowable from the moves;
   the _as applicable_ credit part is collection timing the moves cannot see. Booking
   the minimum and carrying the rest to 485 is the only default that never over-settles.
5. **423 gated on variable boxes, else 424; purchases mirror to 526/527.** The guide's
   423 gate (reduced-rate taxpayer) is read as a conjunction: lower rate _and_ variable
   boxes present. Without variable-rate taxes in the chart, 423 stays 0.0 rather than
   guessed.
6. **609 and 721–731 read tags, zero until the withhold flow.** Their documents belong
   to `l10n_ec_withhold`, not to this addon; fabricating them from unrelated moves would
   put invented withholdings in a return.
7. **Carryovers default to 0.0 as named wizard inputs.** A prefill that silently invents
   prior-period balances is worse than one that asks. Storing prior filings is a stated
   v2 glue (`l10n_ec_104_balances`).

## Consequences

- The collector sums fixed box lists (D1, D3); adding a chart tax with a new tag flows
  in with no code change, adding a new box needs a list edit plus a test -- both
  deliberate.
- Every decision carries a test pinning it (totals with 5% lines, 563 at 0.5 and at
  empty sales, 429 with a 424 adjustment, cash/credit split, 423-at-zero without
  variable rates), so an overturned reading fails loud instead of drifting.
