This module currently ships the `l10n.ec.temporal` mixin, the SRI referential
catalogs, and the ATS schema layer. There is nothing to configure and no menu,
no wizard and no ATS builder yet: document generation arrives in a later task of
the same project.

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