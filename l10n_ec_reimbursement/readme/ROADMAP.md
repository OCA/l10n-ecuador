# Roadmap

Out of scope in v1, with rationale and a v2 proposal.

| Item | Why out of v1 | v2 proposal |
|---|---|---|
| File `totbasesImpReemb` and `reembolsos` rows in the ATS document | `l10n_ec_ats` withholds both as out of v1 scope, and a withheld key in a row refuses generation; changing the builder lives outside this module | Emit `totbasesImpReemb` (and the ATS `reembolso` detail rows) from the builder once that scope lands |
| ICE legs in the EDI block | `detalleImpuesto` needs an ICE tariff code the leg does not store; any ICE amount refuses the emission instead of filing a guessed rate | Add ICE tariff-code (and base) fields to the leg, then emit the `codigo 3` row |
| Sustento x document cross-check | Frappe validates sustento x tipoComprobante (Tabla 5); v1 records the legs without re-deriving the sustento discipline | Validate the bill's sustento against the leg codes, reusing the ATS catalogue |
