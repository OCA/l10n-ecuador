# ADR 0001: the layout mutates, v1 pins the current one

Date: 2026-10-12. Status: accepted (v1).

## Context

`FORMULARIO RETENCIONES EN LA FUENTE.xls` carries twelve sheets, one layout per validity
window from 2019 to August 2026. Boxes appear (3440, sports-betting 348x, donations
349x), split (312 → 3120/3121) and change meaning across sheets. A collector hardcoding
one layout files wrong the month the SRI publishes the next one -- and the SRI publishes
roughly one a year.

## Decision

v1 implements the `Formulario RF desde ago 2026` sheet and says so in every docstring
that touches a box list. The version selector (period → layout, temporal like
`l10n.ec.temporal` in the ATS addon) is designed but explicitly out of v1: it needs the
twelve sheets parsed into effective-dated box rows, which is its own module-sized task
with its own tests (one layout diff per sheet).

## Consequences

- Filing a period predating ago-2026 with this module is user error, and the README says
  so; the wizard does not date-check beyond the 2000 floor on purpose (the floor is
  physics, the layout is policy).
- When the selector lands, the D5 rule in `readme/DESIGN.md` is the test that fails
  first: it pins the current layout by name.
- The twelve sheets ship under `docs/reference/` so the selector's author parses exactly
  what v1 was built against.
