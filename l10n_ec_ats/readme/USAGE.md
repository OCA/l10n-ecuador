This module ships the `l10n.ec.temporal` mixin, the effective-dated SRI
referential catalogs, the collectors, the builder, the business validators, the
schema layer, and the wizard that composes them.

## Generating a month

`l10n.ec.ats.generate` takes a company, a year and a month, and produces one
`AT{mmaaaa}.zip` holding a single XML that passes `ats.xsd`:

```python
wizard = env["l10n.ec.ats.generate"].create(
    {"company_id": company.id, "anio": 2026, "mes": 8}
)
action = wizard.generate()   # {"type": "ir.actions.act_url", "url": "/web/content/<id>?download=true"}
```

The same call works from a form, a menu entry, an automated action, RPC or a
shell. In the interface it is **Invoicing ‣ SRI ‣ ATS**, a dialog asking for the
company, the year and the month with a single **Generate** button.

The archive name follows ficha técnica §1.2: `AT` then the month then the year,
both zero-padded, no separator and no special character, so March 2026 is
`AT032026.zip`. Inside it there is exactly one member, `AT{mmaaaa}.xml`. The
file is attached to the wizard record and downloaded through `/web/content`, so
the bytes a user saves are the bytes that were validated.

## When generation is refused

Everything wrong with a period arrives in **one** `UserError`, numbered, and no
file is produced. One error per lookup would make a bad period unreadable, and a
file that quietly omitted the unusable documents is the failure the project
exists to prevent. The message always ends by saying that nothing was assumed.

Four things stop generation, and each names the table, the code and the window:

| What | How it is reached |
| --- | --- |
| a **catalog gap** — no entry covers the reported day | shipped data: `Tabla 13` publishes the card payment forms from 2016-05-01, so a sale declaring form `20` in March 2016 cannot be filed |
| a **catalog overlap** — two entries claim the same day | the wizard's preflight resolves `Tabla 12` as a whole, because a second regime in force at once is an overlap even under a different code |
| an **`unresolved` `Tabla 3.10` rate** — the source states no single number | the preflight reads the concepts off the **documents**, before collection drops anything; 1689 of the 3149 rates carry no percentage |
| **missing source data** — a field no record can supply | the collectors return the error rather than raising, and the wizard aggregates it. A vendor bill with no SRI authorization is the canonical case: Odoo Enterprise fabricates `'9999999999'` and ATS refuses the file |

The period itself is refused earlier, by the field: a year before 2000 or a
month outside 1..12 never reaches a collector.

## Warnings do not block

`ESQUEMA` row 22 calls a `montoIva` that differs from
`baseImpGrav x porcentajeIva` a *mensaje de advertencia*, while the six
IVA-withholding rows call an excess over `montoIva` *grave*. Both come back from
`l10n.ec.ats.generate._l10n_ec_run()` as `(attachment, violations)`; only the
`blocking` ones stop the file, and both severities are returned so a caller can
report an *alerta* without refusing a return the SRI would accept.

**`generate()` writes the non-blocking ones into the wizard's `warnings` field,
which the form renders.** They are not an exception: an *alerta* by definition
does not stop a return the SRI accepts, and raising one would make an acceptable
return unfileable. Odoo 19 has no non-raising user-facing exception to use
instead — `odoo.exceptions` carries no `Warning` and no `Notification`, and
`from odoo.exceptions import Warning` is what the repository's mandatory
`odoo-exception-warning` check exists to refuse. The `{"warning": ...}` dict a
button returns is the **onchange** contract (`odoo.orm.models._onchange_eval`),
and nothing in the action path reads it. So the download still happens and the
findings are on screen next to the button that produced them.

```python
action = wizard.generate()
if wizard.warnings:
    _logger.info(wizard.warnings)
```

A programmatic caller can skip the field and read the severities itself:

```python
attachment, violations = wizard._l10n_ec_run()
for violation in violations:
    _logger.info("%s -- %s", violation.rule, violation)
```

## Reading a historical period

The reported period is the **only** input. Every catalog read resolves through
`_applicable_on(last day of the reported month)`, so loading 2016-06 against a
file of `Tabla 12`'s 14% regime, `Tabla 3.10`'s 8% `porcentajeAir` for concept
`304` and the `Tabla 13` forms of that month produces a genuinely different
document from 2026-08 — not the same file with a different header. The test
`test_historical_period_files_a_different_document` pins exactly that: two
periods, one fixture, and the only value that differs is the one read out of the
catalog.

**`valorRetIva` of `0.00` is not an error.** `ESQUEMA` row 24 reads *"Debe ser
igual a la baseImpGrav aplicando el porcentajeIva (tabla 11). El valor puede ser
mayor o igual, **si no existe valor colocar 0.00**"*. The cell sanctions `0.00`
explicitly, so a `ventas` row whose client withheld **no** IVA is filed as
`0.00` and produces no finding — which matters because a company whose clients
do not withhold IVA is most companies, and refusing those rows would make a sales
period unfileable. A **non-zero** value is checked against the `Tabla 11` shares
in force for the reported period and a value matching no single share is an
*alerta*, never a grave one: a row aggregates every withholding for one client
and document type, so a blend of regimes is legitimate, and exceeding a share is
what *"puede ser mayor o igual"* exists to permit. See `ROADMAP.md` for the
reading this replaced.

## Validating an ATS document

`l10n_ec_ats.schema` exposes the schema layer and nothing else. No model, no
menu, no configuration:

```python
from odoo.addons.l10n_ec_ats.schema import ATS_XSD_PATH, validate_ats_xml

result = validate_ats_xml(xml_string)
if not result.is_valid:
    raise UserError("\n".join(result.errors))
```

`validate_ats_xml` accepts `str` or `bytes` and returns an
`AtsValidationResult(is_valid, errors)`. It never raises for bad input: an
unparseable document comes back as `is_valid=False` with the parser message in
`errors`, because the caller may be validating text it did not just build.
`errors` is empty exactly when `is_valid` is true.

## The schema is grammar, not the norm

`data/xsd/ats.xsd` is the schema the SRI publishes. It is shipped normalized,
because the repository's own quality gate (`trailing-whitespace`,
`end-of-file-fixer`, `mixed-line-ending --fix=lf`) rewrites any file it
classifies as text and it classifies `.xsd`: a byte-identical copy would leave
`pre-commit run` red on every checkout. Exactly four mechanical changes were
applied — BOM removed, declaration corrected to `UTF-8`, CRLF converted to LF,
trailing whitespace stripped from 14 lines — and they are listed in the header
of the file itself. No type, facet, pattern or element was touched. Tests pin
the sha256 of both the upstream artifact and the shipped copy, so the
normalization cannot be widened unnoticed.

Read the schema as authoritative for **lexical shape, cardinality and patterns**
and as **not** authoritative for business rules. It is more permissive than the
norm, and three behaviours prove it, all pinned by tests:

- `totalVentas` may be **negative**. `monedaType` may not. A credit note cannot
  be expressed by negating a line amount, so the aggregate and the lines are
  not interchangeable.
- `31/02/2020` is a **valid date**. `fechaType` bounds the day to 01-31 and the
  month to 01-12 and never relates them to a calendar.
- The deprecated `estabRetencion2` … `fechaEmiRet2` family is **still accepted**,
  annotated "eliminado se mantiene por compatibilidad". Emit nothing.

The same file declares `establecimientoType` as a plain three-digit string with
no lower bound, so `establecimiento` of `000` validates even though
`minExclusive 000` does exist — on `numEstabRuc` and on `codEstab` only. A zero
establishment code has to be rejected by this module, not by the schema.

Two further limits are worth stating plainly. The schema declares eight
`xsd:enumeration` facets in total and **none** of them is a VAT rate, a
withholding concept or a document type, so every code list is only a loose
pattern. And `razonSocial` / `denoProv` are whitelisted to
`[a-zA-Z0-9\s]`: not only accents but all punctuation must be stripped, so
`SA de CV` and `S.R.L.` have to be reduced rather than transliterated.

None of that is a reason to edit the schema. Two validation layers are
required: this one for grammar, and one built from the SRI catalog's
`Validaciones` column for the business rules.

## Catalog semantics

The semantics the rest of the ATS work depends on are these:

- A window is **inclusive of both endpoints**. A record applies on date `d`
  when `date_start <= d` and (`date_end` is null or `d <= date_end`).
- A null `date_end` means **open-ended**, not "invalid". It applies
  arbitrarily far into the future.
- `date_start > date_end` is a **data error** and raises a `ValidationError`.
- Two windows **overlap** when they share at least one day. `2024-01-31` and
  `2024-02-01` are adjacent, not overlapping.
- The union of the windows of one series should be **contiguous**. A hole
  means a period the SRI covered and the catalog does not.

Models that inherit the mixin gain `date_start` and `date_end` fields plus:

- `_applicable_on(date)`: the recordset applicable on `date`.
- `_temporal_overlapping(other)`: whether two windows intersect.
- `_temporal_gaps(key)`: the uncovered ranges inside one series, where `key`
  is the caller-supplied domain identifying the series.