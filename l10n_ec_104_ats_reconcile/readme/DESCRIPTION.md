This module reconciles the Form 104 aggregates of one month against the
ATS blocks of the same month: Σ `ventasEstab` (net per establishment)
against the 104's 419, and Σ `montoIva` (absolute per row) against the
104's 429 rebuilt gross with twice the credit-note tax.

The gross/net split is the whole point: ATS `totalVentas` sums
credit-note magnitudes while the 104 nets them, so a direct comparison
drifts by twice the notes every month with returns. A drift names its
amounts on both sides; a period the ATS cannot build is refused with its
reasons rather than reconciled partially.
