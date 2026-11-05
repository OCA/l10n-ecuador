Reconciling a month:

`l10n.ec.104.ats.reconcile` takes a company, a year and a month, runs both
collectors over the same posted moves, and reports one verdict per check.

In the interface it is **Invoicing ‣ SRI ‣ 104 vs ATS**, a dialog asking
for the company, the year and the month with a single **Reconcile**
button. The button offers a CSV download and renders the verdict on
screen: `MATCH`, or `DRIFT` with the ATS and 104 amounts side by side.

A period the ATS cannot build (an unfilable document, a catalog gap)
arrives in **one** `UserError` with the ATS reasons, and no verdict is
produced. Reconciling against a partial ATS side would bless a file the
company never had.
