Prefilling a month:

`l10n.ec.103.generate` takes a company, a year and a month, and pre-fills
every derivable box of that month's Form 103 from its posted moves: the
resident block, the non-resident block and the totals.

In the interface it is **Invoicing ‣ SRI ‣ Form 103 (Withholding)**, a
dialog asking for the company, the year and the month with a single
**Prefill** button. The button offers a CSV download
(`formulario_103_YYYYMM.csv`) with concepto→valor pairs -- the shape the
SRI XML/JSON upload guide asks for -- and renders the same boxes on
screen. The filing itself happens in the SRI portal: carry the values
over, review the 500 compensation you filled, and complete the manual
boxes there.

The 500 compensation (undistributed-profit advance, art. 39.2.1 LRTI) is
not derived: fill `carryover_500` from your dividends reading before
pressing Prefill. It defaults to zero and is reported as carried, never
as computed.

Everything that cannot be derived arrives in **one** `UserError`, numbered,
and no file is produced. A company filing outside Ecuador is refused the
same way. Nothing is computed and nothing is assumed on refusal.
