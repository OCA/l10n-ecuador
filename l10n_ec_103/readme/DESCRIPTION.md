This module pre-fills the boxes of the SRI monthly withholding return
(Formulario 103) that derive from the posted moves of the reported month,
with traceability from every prefilled box back to its documents.

It does not reimplement what Odoo core already computes: the 103 report of
`l10n_ec` (engine `tax_tags`) already derives the resident and
non-resident concept lines. Those boxes are read, never recalculated. What
this module adds is the layer core does not ship: the subtotals (349/399,
497/498), the totals (499/501), the concepto→valor upload file, and the
wizard that composes them with the manual boxes (payroll, dividends,
special regimes, payments).
