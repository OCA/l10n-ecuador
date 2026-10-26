# Roadmap

Out of scope in v1, with rationale and a v2 proposal. Each entry states the
evidence and what a future version would need.

| Boxes | Why out of v1 | Evidence | v2 proposal |
|---|---|---|---|
| Payroll under dependent relation (302/352) | HR payroll has no source in moves | Form boxes 302, 352 | Manual boxes fed from payroll, never derived |
| Dividends (325-331 / 375-381) and non-resident dividends (404-407, 415-418, 425-428 / serv) | Board deeds and shareholder composition, user assertion | Form boxes 325-331, 404-407 and peers | Manual boxes with deed traceability |
| IRU banana / sports betting / donations (3xxx/39xx) | Sector registries (boxes, deeds, MAG/SENAE data) absent from Odoo | Form boxes 5100-3998 | Sector glue, only for those taxpayers |
| Payment section (890, 897/898/899, 880, 902/903/904/999) | Treasury/post-filing, not accounting | Form boxes 890-999 | `l10n_ec_103_payment` glue |
| Treaty classification (con/contra convenio, paraísos) | Needs treaty + haven lists resolved per payee | Form sections 402-433 | Input classification per partner, then derivation |
| Form-version resolution across the 12 published layouts | The layout mutates (2019 → ago 2026); v1 pins the current one | `FORMULARIO RETENCIONES EN LA FUENTE.xls`, 12 sheets | Temporal selector periodo→versión (first ADR) |
| Purchase-side ATS reconciliation | Needs the ATS instalable chain first | Same seam as `l10n_ec_104_ats_reconcile` | `l10n_ec_103_ats_reconcile` glue |
