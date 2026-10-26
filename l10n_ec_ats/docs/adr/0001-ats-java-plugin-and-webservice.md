# ADR 0001 — The Java plugin and DIMM web service are excluded; local XSD validation is in scope

- **Status:** accepted
- **Date:** 2026-10-03
- **Supersedes:** nothing
- **Referenced by:** `odd/tasks/l10n_ec_ats.md` §4.2 (out-of-scope table, Java plugin
  row)
- **Companion:** [ADR 0002 — ATS design decisions](0002-ats-design-decisions.md)

## Context

The SRI publishes an ATS validation tool as `ats.plugin.1.19.0.zip`: an Eclipse/OSGi
bundle exposing `ec.gob.sri.dimm.ats.*`, built around DIMM 1.19.0. A DIMM installation
also exposes a web service that accepts a candidate ATS and answers whether the SRI
would accept it.

That tool is the only artifact the SRI ships which actually _rejects_ a file. Everything
else available to a developer — the XLS catalogs, the ficha técnica, the XSD — describes
the format, and the XSD is demonstrably more permissive than the norm.

So the choice is not "validate or not". It is _which_ validator, and that choice
determines whether this addon can exist in the community at all.

## Decision

**The Java plugin and the DIMM web service are out of scope. Validation is performed
against the SRI's published XSD, shipped inside this addon.**

This is a permanent exclusion for the Java plugin, not a deferral. The web-service route
is deferred, not excluded, and is described under Alternatives.

### Why the Java plugin is permanently excluded

1. **It is an OSGi/Eclipse bundle.** Depending on it means depending on an Eclipse
   runtime inside an Odoo process. That is not shippable in a PyPI wheel, not
   installable by `pip`, and not acceptable to the OCA.
2. **It requires a local DIMM installation** with its own database, its own updater and
   its own licence acceptance. An OCA addon may not require the user to install and
   maintain a second desktop application to validate a return.
3. **There is no maintained Python port.** The algorithm is implemented in Java only.

The plugin is therefore not merely inconvenient — it is structurally incompatible with
the distribution channel.

### Why local XSD validation _is_ in scope

1. **The XSD is shipped and auditable.** `l10n_ec_ats/data/xsd/ats.xsd` is the SRI's own
   artifact, byte-normalised in a documented, tested way. `ATS-04`'s fixtures pin what
   it actually accepts and rejects, including the places where it is _wrong_.
2. **The mechanism already exists in this repository.** `l10n_ec_account_edi` validates
   outbound EDI documents against a shipped XSD. Reusing that pattern adds no new
   concept to the localization.
3. **It is the only layer available to every user.** A check that only runs for
   contributors with DIMM installed is not a control over data completeness, which is
   what this project was asked for.

### The XSD is not sufficient, and this is the load-bearing consequence

Validating against the XSD is necessary and **not sufficient**. The XSD accepts
`establecimiento="000"` and `puntoEmision="000"`, accepts impossible dates such as
`31/02/2020`, and knows nothing about the `Validaciones` rules, the ficha's ceilings, or
the SRI's catalog eras.

This is why the addon has three layers — XSD, business validators, catalog preflight —
instead of one. **The XSD is the weakest of the three.** Any proposal to add validation
must be judged against that baseline: if the XSD accepts it, the addon still has to
decide whether the norm permits it.

## Consequences

- The addon installs and runs with no external dependency. Nothing to download, nothing
  to licence, nothing to keep in sync.
- Validation is deterministic and unit-testable, which is what made 408 tests possible.
- **Some defects of the SRI's own toolchain are ours to catch.** Where the XSD is
  permissive, the business layer closes the gap and says so in `readme/DESIGN.md`.
- We do not inherit DIMM's behaviour on any question where DIMM and the ficha disagree.
  Where DIMM is the only evidence for a rule, this addon has no opinion and the question
  goes to `readme/ROADMAP.md` rather than being guessed.

## Alternatives considered

### Call the DIMM web service at validation time — deferred, and the design is pre-committed

If the plugin is ever unblocked, the web service is the better target than the plugin:
no local install, no OSGi.

**The shape is fixed now, while it is cheap.** When this happens, validation becomes a
_web service behind a validator interface_, so the collection and builder layers stay
untouched. The builder already produces a complete document string and the wizard
already owns the point in the pipeline where acceptance is decided, so the seam is a
single call in one place. Adopting this ADR later must not require touching
`l10n_ec_ats_collector.py` or `l10n_ec_ats/builder.py` — that is the property being
bought by deciding the shape now.

A web-service call is **not** a silent fallback: if it is unavailable, generation must
fail or the user must be told the file was not remotely validated. Silently reporting
success for a check that did not run is exactly the failure mode this project forbids.

### Write a Python reimplementation of the plugin's algorithm — rejected

It would be a permanent maintenance liability reimplementing an undocumented algorithm
that changes with DIMM versions, with no way to detect divergence. Shipping the XSD plus
explicit business rules keeps every judgement we make visible and reviewable; a
reimplementation would hide them.

### Rely on DIMM only — rejected

It is the strongest oracle available, but requiring it makes the addon unusable for the
community and makes the control over data completeness contingent on a desktop
application the user may not have.

## Notes for whoever picks this up

- The XSD shipped here has **different line numbers from the upstream SRI file**. A
  citation of the form `ats.xsd:1468` in an upstream docstring cannot be opened at that
  line in this repository; the normalisation that shifts it is documented in the file's
  own header.
- Do not treat XSD acceptance as compliance. See "The XSD is not sufficient" above.
