# Roadmap

Out of scope in v1, with rationale and a v2 proposal. Each entry states the
evidence and what a future version would need.

| Boxes | Why out of v1 | Evidence | v2 proposal |
|---|---|---|---|
| Prior-month balances and carryovers (605-608 carried, 615/617/618/619 carried, 483) | Inter-period state, not derivable from the month's moves | Form boxes 605-608, 615, 617-619, 483 | `l10n_ec_104_balances` glue reading prior filings + withholdings received (609) |
| Payments, sustitutivas, interest/fines (890, 897/898/899, 902/903/904/999, 880) | Treasury/post-filing, not accounting | Form boxes 890, 897-899, 902-904, 999, 880 | `l10n_ec_104_payment` glue |
| Compensations and sector benefits (603, 604, 607/608, 610-614, 622, 624/625) | Require case files and resolutions, user assertion | Form boxes 603-604, 607-608, 610-614, 622, 624-625 | Manual boxes with audit trail, never derived |
| Merger/absorption (623, 492) | Requires mercantile-registry deed, one-off event | Form boxes 623, 492 | Manual box gated on deed date |
| ISD refund for exporters (700/701/702) | Needs customs/FUE data model absent from Odoo | Form boxes 700-702 | Export document model (shared gap with ATS) |
| Unpaid withholdings, public sector (802) | Sector-specific settlement state | Form box 802 | Manual box for public entities |
| COVID deferred payment (881-887), presumptive gambling (621) | Expired/special regimes with own registries | Form boxes 881-887, 621 | Only on explicit maintainer decision |
| Tourism variable rate (203) | Needs executive decree + Tourism Ministry cadastre | Form box 203 | Rate table resolved for the reported period |
| RIMPE semestrial filing | Period rule (June/December under code 2011), not extra boxes | SRI guide, RIMPE regime | Wizard period option, no new boxes |
| Informative reimbursements (434/444/454, 535/545/555), non-object/exempt (431/441, 531/541, 532/542) | Informative-only in v1, no own apportionment | Form boxes 431, 434, 531-532, 535 | Reported as-is; apportionment only if the SRI requires it |

Reconciliation of box 429 against the ATS `totalVentas` header is a separate
follow-up (`l10n_ec_104_ats_reconcile`), never a condition of this module:
the ATS derives `totalVentas` from its `ventas` rows while the 104 reads 429
from tags, and wiring them together here would couple this PR to the open ATS
PR (#105).
