# Design

One table per ATS block, mapping every element of the document to the record it
is read from, the method that reads it, the SRI catalog that validates it and
the rule that rejects it. It exists so a reviewer can check the work without
reading 4,000 lines of Python.

## How to read this document

| Column | What it points at |
| --- | --- |
| **ATS element** | The name in `data/xsd/ats.xsd`. Not the ESQUEMA sheet's spelling — the sheet writes `autorización` with an accent in one row, the schema does not. |
| **Source of truth in Odoo** | The record the value is read from, or **absent** when the builder declares the element and nothing may emit it. |
| **Collector method** | `models/l10n_ec_ats_collector.py` unless stated. Line numbers are the ones in this repository. |
| **Catalog table** | The `l10n.ec.ats.catalog.table` code resolved through `_applicable_on()`, or `—` for an element no catalog constrains. `Tabla 3.10` has no registry row: it is split across `l10n.ec.ats.income.withholding.concept` and `.rate`. |
| **Validator rule** | The `rule` string a blocking or advisory `AtsViolation` carries, or the builder's refusal. `⚠` marks a **warning** that is reported and does not stop generation. |

Two abbreviations recur. **`!k`** marks an element the schema types `totalVentasType`
(`data/xsd/ats.xsd:1337`) — the only amount type whose pattern admits a leading
minus. **«absent»** marks an element the schema declares and this addon never
emits; `builder.py` refuses a payload that carries one rather than dropping it,
and states why in the error message.

**Every catalog read resolves for the reported period.** `reported` in a source
column means `period_start`, the first day of the month being filed — never the
document's own date. The ficha requires `fechaRegistro` to *equal* the reported
period, so that is the day a code's validity window is judged against.

---

## 1. `iva` — the header (`builder.ATS_HEADER_SPEC`, `builder.py:569`)

Fifteen children in `ivaType`'s declared order (`data/xsd/ats.xsd:624`). The
order is normative and non-obvious: the three optional scalars sit **between**
`Mes` and `codigoOperativo`, so a builder that emits mandatory fields first is
wrong.

| ATS element | Source of truth in Odoo | Collector method | Catalog table | Validator rule |
| --- | --- | --- | --- | --- |
| `TipoIDInformante` | — **literal `"R"`** | wizard `_l10n_ec_header` (`wizard/l10n_ec_ats_generate.py:573`) | — | `builder.HEADER_ENUMERATED_VALUES` (`:1049`) refuses anything else |
| `IdInformante` | `company.partner_id.vat` | wizard `_l10n_ec_header` (`:595`) | `02` for the RUC branch | `identificacion.ruc` — module-11 check digit, unconditional (`validators.py:714`) |
| `razonSocial` | `company.l10n_ec_business_name` ‖ `partner_id.name` | wizard `_l10n_ec_business_name` (`:605`) | — | `builder._render_text` (`:679`): NFKD, whitelist `[a-zA-Z0-9\s]`, ≥ 5 chars on the **reduced** string |
| `Anio` | `wizard.anio` | wizard `_l10n_ec_header` (`:597`) | `01` | `periodo.anio` — ≥ 2000 (`validators.py:844`); `periodo.cabecera` — must equal the resolved period |
| `Mes` | `wizard.mes` rendered `%02d` | wizard `_l10n_ec_month_code` (`:231`) | `01` via `_l10n_ec_month_entry` (`:241`) | `periodo.cabecera` (`:858`) |
| `regimenMicroempresa` | `company.l10n_ec_regimen` **and** the month's `Tabla 01` description naming a *semestre* | wizard `_l10n_ec_regimen_microempresa` (`:620`) | `01` | — derived, never asserted |
| `numEstabRuc` !k | `len(ventasEstablecimiento rows)`, zero-padded to 3 | `_l10n_ec_num_estab_ruc` (`:2122`) | — | `periodo.num_estab_ruc_nonzero`, `periodo.num_estab_ruc_recuento` (`:875`, `:887`); `establecimiento.no_000` |
| `totalVentas` !k | Σ of the three base buckets over the **`ventas` rows** | `_l10n_ec_total_ventas` (`:2138`) | — | `total_ventas.sumatoria` (`:909`), `ventas_estab.tope` (`:929`) |
| `codigoOperativo` | — **literal `"IVA"`** | wizard `_l10n_ec_header` (`:599`) | — | `builder.HEADER_ENUMERATED_VALUES` |
| `compras`, `ventas`, `ventasEstablecimiento`, `anulados` | the four collectors | `collect_iva_header*` takes **both** sales blocks as required arguments (`:2054`) | — | see §2–§5 |
| `exportaciones`, `fideicomisos`, `rendFinancieros` | «absent» — out of scope, see §7 | declared `_withheld(..., _V1_NOT_IN_SCOPE)` (`builder.py:598-602`) | `06`, `07.1`, `10`, `18`, `19` **not loaded** | refused by name if a payload carries one |
| `recap` | «absent» — Tipo 2 contributor | `_withheld(..., _TIPO_TWO_ONLY)` (`builder.py:599`) | `08` **not loaded** | refused by name |
| `establecimientoRecap` | «absent» — `estRecapType`, **two** digits, inside `recap` | `ATS_ESTABLECIMIENTO_RECAP_NAME` (`builder.py:611`) | — | `builder._check_header_keys` (`:1034`) — its own message, because the reason is the **width** |

`collect_iva_header(ventas_rows, ventas_establecimiento_rows)` requires both
blocks as arguments on purpose: the relationship between the header and the
blocks is the entire content of these two fields, so a caller cannot obtain one
without the other and cannot wire them to different periods. `totalVentas` is
read out of the `ventas` rows and never re-aggregated from the documents — the
ficha calls it a *casillero no editable*, and a second pass is how a header and
its own block drift apart.

---

## 2. `compras` — one row per document (`builder.ATS_COMPRAS_SPEC`, `builder.py:401`)

`detalleComprasType` (`data/xsd/ats.xsd:743`) is a strict `xsd:sequence`, so the
order below **is** the content model. All forty-six elements are declared in the
spec, emitted or not, so the spec can be diffed against the artifact in full.
Selection: `move_type in ('in_invoice','in_refund')`, `state = 'posted'`,
`company_id`, `move.date` in the window (`_l10n_ec_compras_moves:215`). A
document with any error yields **no** row — a partial row is not returned
(`_l10n_ec_compras_row:293`).

| ATS element | Source of truth in Odoo | Collector method | Catalog table | Validator rule |
| --- | --- | --- | --- | --- |
| `codSustento` | `move.l10n_ec_tax_support` (`Char(2)`, captured) | `_l10n_ec_cod_sustento` (`:413`) | `05` | `_l10n_ec_resolve_entry("05")` — the rejection lists the codes **read from the catalog** |
| `tpIdProv` | `PartnerIdTypeEc.get_ats_code_for_partner(partner, "in_invoice")` | `_l10n_ec_tp_id_prov` (`:483`) | `02`, then `A` via `_l10n_ec_transaction_type_resolves` (`:547`) | Consumer Final refused on the purchase side; `identificacion.ruc` when the row is a RUC |
| `idProv` | `partner.vat` | `_l10n_ec_id_prov` (`:571`) | — | all-zero placeholder refused |
| `tipoComprobante` | `move.l10n_latam_document_type_id.code` | `_l10n_ec_tipo_comprobante` (`:438`) | `04` **and** `05` — the support's `document_type_codes` must cover it | reported when the cross-check fails |
| `tipoProv` | `Tabla 14` row matching `partner.company_type` | `_l10n_ec_conditional_province` (`:614`) → `_l10n_ec_tabla_14_entry` (`:668`) | `14` | emitted only for the passport identification; absent key ⇒ absent element |
| `denoProv` | `partner.name`, accent-stripped | same (`:647`) | `14` | `builder._render_text`, `denoProvType` whitelist, ≥ 1 char |
| `parteRel` | `partner.l10n_ec_related_party` → `SI`/`NO` | `_l10n_ec_parte_rel` (`:604`) | — | user assertion, not a derivation; unchecked means `NO` |
| `fechaRegistro` | `move.date` | `_l10n_ec_fecha` (`:2643`) | — | `fecha_registro.periodo` — must equal the reported month (`:1179`) |
| `establecimiento` | **the supplier's**, from the document number | `_l10n_ec_document_triple` (`:682`) | — | `establecimiento.no_000` (`:727`) + builder `no_zero` |
| `puntoEmision` | same triple | same | — | same |
| `secuencial` | same triple | same | — | `builder` `\d{1,9}`; not checked as a number here (only `anulados` needs that) |
| `fechaEmision` | `move.invoice_date` | `_l10n_ec_fecha_emision` (`:813`) | — | `fecha_emision.registro`, `fecha_emision.anio`, `fecha_emision.periodo` (`:1193`-`:1215`) |
| `autorizacion` | `move.l10n_ec_authorization_number` | `_l10n_ec_autorizacion` (`:780`) | — | `\d{3,49}`; **missing ⇒ refused**, never `'9999999999'` |
| `baseNoGraIva` | Σ `base_amount` where `tax_group_id.l10n_ec_type = 'not_charged_vat'` | `_l10n_ec_compras_amounts` (`:876`), `BASE_TYPES` (`:42`) | — | bounded, never negative (`monedaType`) |
| `baseImponible` | `'zero_vat'` | same | — | same |
| `baseImpGrav` | every `vat*` group, read from the **field's own selection** | `_l10n_ec_gravable_vat_types` (`:862`) | — | `compras.monto_iva_tope`, ⚠`compras.monto_iva` (`:1243`, `:1255`) |
| `baseImpExe` | `'exempt_vat'` | `BASE_TYPES` (`:45`) | — | present on compras only; absent from `detalleVentasType` |
| `montoIce` | `ice` group, `tax_amount` | `ICE_TYPES` (`:106`) | — | `compras.monto_ice` (`:1228`) — may not exceed the three bases |
| `montoIva` | every `vat*` group, `tax_amount` | (`:900`) | `12` for the expected share | `compras.monto_iva_tope`; ⚠`compras.monto_iva` — the cell says *advertencia* |
| `valRetBien10`, `valRetServ20`, `valorRetBienes`, `valRetServ50`, `valorRetServicios`, `valRetServ100` | posted **purchase** withholding lines → `l10n_ec_withhold_tax_amount`, bucketed by the tax's rate | `_l10n_ec_iva_withholdings` (`:956`), `IVA_RETENTION_ELEMENTS` (`:27`), `_l10n_ec_withholding_lines` (`:926`) | `11` — the rate must be published, exactly one entry | ⚠`compras.retencion_iva_cuota`; `compras.retenciones_tope` — *la validación es grave* (`:1031`) |
| `formasDePago` / `formaPago` | `move.l10n_ec_sri_payment_id.code` | `_l10n_ec_formas_de_pago` (`:1141`) | `13` | `compras.forma_pago_obligatoria` above USD 1,000.00 (`:1314`), `compras.forma_pago_duplicada` |
| `air` / `detalleAir` | see §2.1 | `_l10n_ec_income_withholdings` (`:1025`) | `Tabla 3.10` | see §2.1 |
| `valorRetencionNc`, `totbasesImpReemb`, `pagoExterior`, `reembolsos`, `docModificado`, `estabModificado`, `ptoEmiModificado`, `secModificado`, `autModificado` | «absent» — v1 scope | `_withheld(..., _V1_NOT_IN_SCOPE)` | `21` loaded but unread | refused by name |
| `estabRetencion1`, `ptoEmiRetencion1`, `secRetencion1`, `autRetencion1`, `fechaEmiRet1` | «absent» — no Odoo record describes a withholding **document** | `_withheld(..., _NO_WITHHOLDING_DOCUMENT)` | — | refused by name |
| `estabRetencion2` … `fechaEmiRet2` | «absent» — *"eliminado se mantiene por compatibilidad"* | `_withheld(..., _COMPATIBILITY_ONLY)` | — | refused by name |

All six `Tabla 11` withholding elements are emitted, defaulting to `0.00`,
because the ficha marks all six obligatory even though `ats.xsd` makes three
optional. That zero is sourced — the catalog published no withholding at that
rate — not substituted.

### 2.1 `air` — the nested income-withholding sub-report

`air` is `maxOccurs="1"` holding unbounded `detalleAir` (`data/xsd/ats.xsd:687`),
so one document with several concepts carries them all in **one** row.
Content model: `detalleAirComprasType` (`:894`), which **extends**
`detalleAirType` — the four mandatory children come first, the five
dividend-payment elements only afterwards. `builder.ATS_AIR_SPEC` (`:368`)
declares all nine in that order.

| ATS element | Source of truth in Odoo | Collector method | Catalog table | Validator rule |
| --- | --- | --- | --- | --- |
| `codRetAir` | `tax.l10n_ec_code_ats` — on the **tax**, not the group: every withholding group shares a generic `"1"`/`"2"` | `_l10n_ec_income_withholdings` (`:1056`) | `Tabla 3.10` concept | concept absent from the table ⇒ reported (`:1078`) |
| `baseImpAir` | `abs(withholding_line.balance)` | (`:1057`) | — | `compras.base_imp_air` / ⚠`…_inferior` against the purchase bases (`:1276`-`:1299`) |
| `porcentajeAir` | **never** a literal: the era's `rate.percentage` | `_l10n_ec_air_rate` (`:1065`), `_applicable_on(reported)` | `Tabla 3.10` rate | 0 or 1 rate ⇒ reported; `unresolved` ⇒ reported with `source_note` (`:1117`) |
| `valRetAir` | `abs(line.l10n_ec_withhold_tax_amount)` | (`:1059`) | — | `compras.val_ret_air` (may not exceed the base), ⚠`…_cuota` |
| `fechaPagoDiv` | «absent» — no dividend record | `_withheld(..., _NO_DIVIDEND_RECORD)` | — | `air.fecha_pago_div` if ever emitted |
| `imRentaSoc`, `anioUtDiv`, `numCajBan`, `precCajBan` | «absent» — no dividend or banana record | `_withheld(..., _NO_DIVIDEND_RECORD)` | — | `air.anio_ut_div`, ⚠`air.im_renta_soc` if ever emitted |

The five conditional elements are refused by `air.emision_condicional` when the
payload carries one and the caller supplied no `AirConditionalCodes`
(`validators.py:1084`) — a check that cannot be made must not be allowed to look
covered. The wizard closes the seam from
`l10n.ec.ats.income.withholding.rate.detail_group` for the reported period
(`_l10n_ec_air_codes`, `wizard/l10n_ec_ats_generate.py:261`): the grouping is a
**dated fact about an era**, which is why it lives on the rate and not on the
code registry.

---

## 3. `ventas` — aggregated (`builder.ATS_VENTAS_SPEC`, `builder.py:479`)

`detalleVentasType` (`data/xsd/ats.xsd:1016`) is narrower than `detalleComprasType`
in three places, and each narrowing is a schema fact rather than a choice: no
`baseImpExe` element, `montoIce` **optional** here and mandatory on compras, and
the six-way `Tabla 11` run collapses into a single `valorRetIva`.

**Entry points:** `collect_ventas(company, date_start, date_finish)` and
`collect_ventas_with_errors(...)` (`:1180`, `:1206`).

**Row key: `(tpIdCliente, idCliente, tipoComprobante, tipoEmision)`**
(`_l10n_ec_ventas_group_key:1262`). `CLAVE PRIMARIA (2)` marks the first three
and does not list `tipoEmision` at all; the ficha settles the gap — the same
document type may be filed again for the same client **provided the emission
type differs**, which is only satisfiable if a differing emission type produces a
row of its own. The key is computed from the **values that reach the file**, so
two client records carrying one identification aggregate into one row. One
unusable member withholds the whole group (`_l10n_ec_ventas_row:1376`): a sum
over a subset is a figure the company never had.

| ATS element | Source of truth in Odoo | Collector method | Catalog table | Validator rule |
| --- | --- | --- | --- | --- |
| `tpIdCliente` | `PartnerIdTypeEc.get_ats_code_for_partner(partner, "out_invoice")` | `_l10n_ec_tp_id_cliente` (`:1379`) | `02`, then `A` | Consumer Final **accepted** here — the opposite of `tpIdProv`. `Tabla 2` publishes `9999999999999` as a sale identification and the ficha's `idCliente` validation names *Consumidor Final*, so refusing it would make the most ordinary Ecuadorian sale unfileable |
| `idCliente` | `partner.vat` | `_l10n_ec_id_cliente` (`:1434`) | — | `identificacion.ruc` when the row is a RUC (`:1396`) |
| `parteRelVtas` | `partner.l10n_ec_related_party` | `_l10n_ec_parte_rel` (`:604`) | — | **omitted** for the final-consumer sentinel (`:1356`) |
| `tipoCliente` | `Tabla 14` row matching `company_type` | `_l10n_ec_conditional_client` (`:1538`) | `14` | only for the passport identification |
| `denoCli` | `partner.name`, accent-stripped | (`:1571`) | — | `denoProvType` whitelist |
| `tipoComprobante` | `l10n_latam_document_type_id.code` | `_l10n_ec_tipo_comprobante_ventas` (`:1445`) → `_l10n_ec_tipo_comprobante_tabla_4` (`:1463`) | `04` | existence only — the ficha's `Código Secuencial Transacción` filter **cannot** be evaluated from the loaded catalog (`Tabla 4` stores two columns for those two ideas) |
| `tipoEmision` | `move.journal_id.l10n_latam_use_documents` — the field core `l10n_ec` itself computes `l10n_ec_require_emission` from — selecting a `Tabla 20` row by its own description | `_l10n_ec_tipo_emision` (`:1493`), `TABLA_20_KEYWORD_BY_USES_DOCUMENTS` (`:92`) | `20` | exactly one row must match, else reported (`:1513`) |
| `numeroComprobantes` | `len(moves)` in the group | (`:1350`) | — | — |
| `baseNoGraIva` | Σ over the group, `'not_charged_vat'` | `_l10n_ec_ventas_amounts` (`:1579`), `VENTAS_BASE_TYPES` (`:54`) | — | bounded, never negative |
| `baseImponible` | `'zero_vat'` | same | — | same |
| `baseImpGrav` | every `vat*` group | `_l10n_ec_ventas_buckets` (`:1617`) | — | ⚠`ventas.monto_iva` |
| `montoIva` | Σ over the group | (`:1605`) | `12` | ⚠`ventas.monto_iva` (`:1420`) |
| `montoIce` | Σ, `ice` group | (`:1611`) | — | `ventas.monto_ice` (`:1407`) — may not exceed `baseImpGrav` |
| `valorRetIva` | posted **sale** withholding lines — `l10n_ec_withholding_type == "sale"` plus a sale-side tax group — `withhold_vat_sale` | `_l10n_ec_ventas_retentions` (`:1636`), `SALE_WITHHOLDING_TYPES` (`:78`) | `11` — rate must be published | ⚠`ventas.valor_ret_iva` (`:1441`). **No floor and no grave branch**: `0.00` produces no finding, and a value matching no single share is an *alerta* |
| `valorRetRenta` | posted sale withholding lines, `withhold_income_sale` | same | — none, deliberately | the block has no per-concept breakdown, so there is nowhere to put a code or a rate |
| `formasDePago` / `formaPago` | every distinct payment form of the group's documents, in booking order | `_l10n_ec_ventas_formas_de_pago` (`:1718`) | `13`, per document | `ventas.forma_pago_duplicada` (`:1458`); **omitted** on a credit note (`:1367`) |
| `compensaciones` | «absent» — `Tabla 21` **is** loaded, but nothing in Odoo records an IVA compensation | `_withheld(..., _NO_COMPENSATION_RECORD)` (`builder.py:498`) | `21` loaded, unread | refused by name |

A credit note is a **row, not a minus sign**: `monedaType` has `minInclusive 0.0`
and `detalleVentasType` has no element that could express a reversal except
`tipoComprobante`, so a refund is filed under its own document type with
absolute amounts (`_l10n_ec_is_credit_note:1745` finds the row in `Tabla 4` by
the phrase the SRI itself uses).

---

## 4. `ventasEstablecimiento` — one row per establishment (`builder.py:521`)

`ventaEstType` (`data/xsd/ats.xsd:1500`) is three elements, and `ventaEst` is
`minOccurs="1"` — the reason an empty wrapper is the one payload shape the
builder turns into **no element** (`_render_block:1005`).

**Row set: the RUC set, not the selling set**
(`_l10n_ec_establishment_codes:1855`). The code is the **union** of two record
sets:

| Source | What it contributes |
| --- | --- |
| distinct `l10n_ec_entity` over the company's **active** journals | every establishment configured, selling or not |
| the entity segment of `l10n_latam_document_number` on the period's **posted sales** documents | every establishment a document was really filed under |

The union is not belt-and-braces: change a journal's `l10n_ec_entity` after a
document was issued and that establishment is left with no journal declaring it,
so reading only the journals drops a real establishment from `numEstabRuc`. A
journal with an **empty** `l10n_ec_entity` is skipped, not emitted —
`sale_withhold_ec` is seeded that way and is active in every EC company. The
union is restricted to sales documents because a vendor bill carries the
**supplier's** triple.

| ATS element | Source of truth in Odoo | Collector method | Catalog table | Validator rule |
| --- | --- | --- | --- | --- |
| `codEstab` | the union above, sorted | `_l10n_ec_establishment_codes` (`:1855`), `_l10n_ec_add_establishment` (`:1902`) | — | `000` reported and the code excluded (`:1922`); `establecimiento.no_000` |
| `ventasEstab` !k | signed sum of the three buckets over the establishment's documents; `out_refund` subtracts | `_l10n_ec_ventas_estab_amount` (`:2010`) | `04` per member | `ventas_estab.tope` — Σ ≤ `totalVentas` (`:929`) |
| `ivaComp` !k | «absent» — same decision as `compensaciones`; `minOccurs="0"` (`data/xsd/ats.xsd:1503`, upstream `:1465`) | `_withheld(..., _NO_COMPENSATION_RECORD)` (`builder.py:524`) | `21` loaded, unread | refused by name |

An establishment that sold nothing still gets a row at `0.00`: the row count is
tied to `numEstabRuc`, which counts establishments *in the RUC*, and dropping
the ones that did not sell is exactly what makes `len(rows) != numEstabRuc`. A
single unusable document withholds the whole row
(`_l10n_ec_ventas_estab_row:1969`).

**`ventasEstab` is net, `totalVentas` is gross — deliberately unequal.**
`ESQUEMA` row 103 defines the block figure as the *net* value, credit notes
subtracted; `ESQUEMA` row 10 defines the header as the sum of three gross
`monedaType` bases. `ats.xsd` is the clincher: `ventasEstab` is typed
`totalVentasType`, the **only** amount type in the schema whose pattern admits a
leading minus, and the SRI gave it to no other element inside Tipo 1. So the
result is `totalVentas ≥ Σ ventasEstab`, with equality exactly when the period
holds no credit note, and a gap of **twice** the credit notes' bases when it
does. A negative `ventasEstab` is real and is **not** clamped.

---

## 5. `anulados` — one row per contiguous run (`builder.ATS_ANULADOS_SPEC`, `builder.py:532`)

**Entry points:** `collect_anulados(company, date_start, date_finish)` and
`collect_anulados_with_errors(...)` (`:2171`, `:2202`).

`detalleAnuladosType` (`data/xsd/ats.xsd:1312`, six elements over the upstream
artifact's `:1312-1321`) is the only block that files a
**range**, and the only one with **no date at all** — no `fechaEmision`, no
`fechaRegistro`. All six elements are obligatory.

**Row key: `(establecimiento, puntoEmision, tipoComprobante, autorizacion)`**
(`_l10n_ec_anulados_group_key:2495`). `CLAVE PRIMARIA (2)` rows 196–201 mark **all
six** elements as *componente de clave general*; the two range fields are
derived, so the other four are read as part of the key. The consequence is worth
stating because the schema does not show it: a run can only ever merge documents
that **share an authorization**, and under electronic invoicing each document
gets its own — so in real data every row is a single document with its number
repeated in both fields. Ranges are the physical-invoicing case.

| ATS element | Source of truth in Odoo | Collector method | Catalog table | Validator rule |
| --- | --- | --- | --- | --- |
| `tipoComprobante` | the **cancelled document's own** `l10n_latam_document_type_id.code` | `_l10n_ec_tipo_comprobante_anulados` (`:2428`) | `04`, *sin filtro alguno* — `ESQUEMA` row 207 | existence only; no `codSustento` cross-check. Code `18` is rejected: it excludes N/C and N/D **by name**, so filing a cancelled credit note under it would assert the cancelled document was not a credit note; `Tabla 2` code `18` (*"COMPROBANTES ANULADOS"*) is unreachable because this block has no `tpIdProv` |
| `establecimiento` | **ours**, from the document number | `_l10n_ec_anulado_triple` (`:2374`) → `_l10n_ec_document_triple` (`:682`) | — | `000` refuses the **whole document** (`:2409`), not part of it |
| `puntoEmision` | same triple | same | — | same |
| `secuencialInicio` | the run's first document's `secuencial` | `_l10n_ec_anulados_runs` (`:2540`), `_l10n_ec_anulados_row` (`:2609`) | — | non-numeric refused (`:2411`); duplicate claimed by two records reported (`:2564`) |
| `secuencialFin` | the run's **last** document's `secuencial` — **repeats `secuencialInicio` for a run of one** | same | — | `ESQUEMA` says *mayor a*; the ficha §2.5 governs (§8) |
| `autorizacion` | `move.l10n_ec_authorization_number` | `_l10n_ec_autorizacion` (`:780`) with its own `missing_message` | — | `\d{3,49}`; a document with none is left out of the range entirely |

Selection: `move_type in ('out_invoice','out_refund')`, `state = 'cancel'`,
**`posted_before`** — which excludes the cancelled draft, because
`button_cancel` accepts a draft and sets `state = 'cancel'`, and
`posted_before` is set in `_post` and by nothing else — `company_id`, and
`move.date` in the window (`_l10n_ec_anulados_moves:2239`).
A refused document is removed from the ranges *before* the runs are built
(`collect_anulados_with_errors:2209`): a range must be built only from documents
that will actually appear in the file, or a row would span a document the file
never reports.

A run breaks wherever the next sequential is not this one **plus one** — which is
exactly where a document that was *not* cancelled sits. Cancelling 5, 6, 7 and 9
is **two** rows (`5`–`7`, `9`–`9`), never one `5`–`9` row. The comparison is
arithmetic on the numbers (`_l10n_ec_sequential_number:2593`), because
contiguity is a property of the value: `9` follows `8` whether they are stored as
`8` or `000000008`.

---

## 6. The resolution seam, and where it bites

Every catalog read goes through `l10n.ec.temporal._applicable_on()` and must
return **exactly one** entry. Zero is a coverage hole, more than one an overlap,
and both stop generation naming the table, the code and the window. There is no
fallback path and no default: **the code that would substitute a literal does not
exist**, which is what makes "no hardcoded values" enforceable rather than
aspirational.

The seam is `_l10n_ec_resolve_entry` (`models/l10n_ec_ats_collector.py:318`) for
the collectors, `validators.resolve_one` / `resolve_rates` / `resolve_regime`
(`validators.py:458`, `:506`, `:482`) for the business layer, and
`resolve_one` / `resolve_regime` again in the wizard's preflight
(`wizard/l10n_ec_ats_generate.py:300`).

Three traps live at that seam and each one costs a wrong rate if forgotten:

| Trap | What happens | Where it is handled |
| --- | --- | --- |
| **`_applicable_on` is `@api.model`** — `search` discards the calling recordset's domain, so `scoped._applicable_on(day)` re-searches the **whole model** | The temporal filter is silently discarded and the lookup returns every era of every table — `Tabla 04`'s 115 entries handed back as though they were `Tabla 12` | Intersect **after** resolving: `CatalogReader._in_force` (`validators.py:424`), `_l10n_ec_applicable_entries` (`:300`), `_l10n_ec_air_codes` (`wizard:261`) |
| **Table codes are zero-padded** (`01`, `02`, `05`), but `Tabla 04` and `Tabla 11` store their **entries** unpadded (`1`, `9`) | An unpadded table number matches nothing, and a lookup that matches nothing resolves to *absent* rather than raising | `validators.TABLA_*` carry the padded forms (`validators.py:396`); entry comparison uses `_l10n_ec_same_code` (`:349`), which forgives leading zeros only |
| **The probe day** | A regime that changed mid-month would make first-day and last-day resolution disagree | `AtsPeriod.catalog_probe` is the **last day** of the reported month (`validators.py:305`), named rather than inlined |

### Catalog inventory

Loaded, with the coverage manifest (`l10n.ec.ats.catalog.table.entry_count`) the
test suite asserts the loaded entries against:

| Table | Title | Entries | Read by | For |
| --- | --- | --- | --- | --- |
| `01` | PERÍODO - MES | 12 | wizard | `Mes`, `regimenMicroempresa` |
| `02` | TIPO DE IDENTIFICACIÓN | 20 | collector, validators | `tpIdProv`, `tpIdCliente`, RUC branch |
| `04` | TIPOS COMPROBANTES AUTORIZADOS | 40 | collector, validators | `tipoComprobante`, credit-note rows |
| `05` | SUSTENTO DEL COMPROBANTE | 16 | collector, wizard preflight | `codSustento` and its document-type cross-check |
| `11` | PORCENTAJES DE RETENCIÓN DE IVA | 6 | collector, validators | the six `Tabla 11` elements and `valorRetIva` |
| `12` | PROCENTAJE DE IVA *(sic)* | 5 | validators, wizard preflight | the IVA rate a `montoIva` is reconciled against |
| `13` | FORMAS DE PAGO / COBRO | 21 | collector | `formaPago` |
| `14` | TIPO DE IDENTIFICACIÓN DEL PROVEEDOR | 2 | collector | `tipoProv`, `tipoCliente` |
| `15` | TIPO DE PAGO | 2 | **nothing** — loaded because `family` mirrors it | — |
| `20` | TIPO DE EMISIÓN FACTURACIÓN | 2 | collector | `tipoEmision` |
| `21` | TIPO DE COMPENSACIONES | 2 | **nothing** — loaded and in scope, unread because no source exists | — |
| `A` | TABLAS REFERENCIALES (A) | 7 | collector | the transaction-type cross-reference `Tabla 2` names |
| `3.10` | *(no registry row)* | 414 concepts / 3149 rates | collector, wizard | `air` |

`Tabla 12` has no code column in the source: the entry `code` is the percentage
rendered as two digits, which is the only table whose `code` repeats across rows.

---

## 7. What is deliberately absent

The out-of-scope blocks are **not** forgotten. Each is declared in
`ATS_HEADER_SPEC` with the reason attached, so the spec can still be compared
against the artifact in full and a payload carrying one is refused with the
reason in the message rather than dropped. `ROADMAP.md` carries the full table
with evidence and a v2 proposal for each.

| Block | Why it is absent | The seam that has to change first |
| --- | --- | --- |
| `recap` | **Tipo 2** contributor (credit-card issuer). `CLAVE PRIMARIA` row 123 marks `establecimientoRecap` as Tipo 2, so the Tipo 1 restriction removes it structurally, not by policy | Issuer-side card data has no Odoo representation. `Tabla 08` is not loaded. |
| `exportaciones` | Needs FUE/DAU, customs district (`Tabla 06`), customs regimes (`Tabla 07.1`), FOB and refrendo. **No Odoo source** and no SRI EDI document for FUE | Deferred on a *data-model* gap, not a policy one — the highest compliance exposure of the four |
| `fideicomisos` | Needs trustee administration: beneficiaries, yields, patrimony, distributions | `Tabla 09` (23 trust types) is not loaded |
| `rendFinancieros` | Financial institutions under Superintendencia de Bancos / Economía Popular. **Excluded by explicit project decision — permanently, not deferred** | None. Never implemented |
| Reembolsos, documentos modificados, pagoExterior, `valorRetencionNc` | v1 scope; the records they need do not exist in Odoo | Declared `«absent»` in the block specs |
| Withholding-document elements (`estabRetencion1`…, `estabRetencion2`…) | No Odoo record describes a withholding document; the `2` family is *"eliminado se mantiene por compatibilidad"* | Declared `«absent»`; nothing may emit one |
| `air`'s dividend and banana extensions | No Odoo record describes a dividend payment or a banana shipment | `detail_group` is loaded as era-scoped data so the **validator** can check the conditional rule; the **collector** still emits nothing |
| `compensaciones`, `ivaComp` | `Tabla 21` **is** loaded — this is a decision about a missing **source**, not a missing table | Needs a field recording an IVA compensation |
| Inbound vendor EDI | Nothing parses a vendor's XML yet, so `compras` types the document triple and the authorization by hand | Tracked as ATS-14, a separate PR discussion |

What a reader can conclude from this document alone: every element of every ATS
block is accounted for in exactly one of two ways — mapped to a record, or
declared absent with the reason the file will print if a payload ever tries to
emit it.

---

## 8. The precedence rule

**The `Validaciones` column governs where the ficha técnica is silent; the
ficha's numbered prose governs where the two conflict.**
(`validators.py:34-62`.) The column is a summary of the DIMM desktop tool's input
screen; the ficha is the filing specification, organised per field. No Odoo
Enterprise behaviour is evidence for either.

It settled two contradictions:

1. **`secuencialFin`** — the column says *"debe ser mayor a secuencialInicio"*;
   ficha §2.5 says *"Para anular un solo comprobante, se debe indicar este
   número en ambos campos."* A strict `>` makes cancelling **one** document
   unrepresentable. The prose wins; `secuencialFin` repeats `secuencialInicio`
   for a run of one (`_l10n_ec_anulados_row:2634`).
2. **`totalVentas`** — the column appends *"Solo Facturación Física F"*; ficha
   §2.1 defines the field with no emission-type restriction and §2.3 bounds
   `ventasEstab` by it. That ceiling is only satisfiable if `totalVentas` counts
   **every** sale, so the three-bucket derivation applies unconditionally.

A third contradiction is settled the same way inside one **sentence**: the
`valorRetIva` cell reads *"El valor puede ser mayor o igual, si no existe valor
colocar 0.00"*. Read the first clause as a floor and the second becomes an error
for every sale whose client withheld nothing. The sanctioned `0.00` settles it —
which is why `valorRetIva` has no floor and no grave branch
(`validators.validate_ventas_row:1434`).

The reasoning, the rejected alternatives and the consequences are recorded in
[`docs/adr/0002-ats-design-decisions.md`](../docs/adr/0002-ats-design-decisions.md).