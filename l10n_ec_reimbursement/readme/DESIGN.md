# Design

One emission carries one code. The SRI XSD allows a single
`codDocReembolso` per info block, so the module refuses a document mixing
reimbursed codes at write time (`_check_single_doc_code`): persisted legs
can never mix, so the emission trusts the stored code. The Frappe side
enforces the same single-code rule.

## Where the nodes land

`factura_V1.1.0.xsd` and `LiquidacionCompra_V1.1.0.xsd` order the nodes as
`infoFactura` (or `infoLiquidacionCompra`), then `detalles`, then
`reembolsos`. The four totals (`codDocReembolso`,
`totalComprobantesReembolso`, `totalBaseImponibleReembolso`,
`totalImpuestoReembolso`) are children of the info element, between
`totalDescuento` and `totalConImpuestos`. The inherit templates therefore
anchor on `//infoFactura/totalDescuento` (resp.
`//infoLiquidacionCompra/totalDescuento`) for the totals and on
`//detalles` for the block. Anchoring the whole injection on the info
element itself would emit `reembolsos` before `detalles` and fail schema
validation.

## One view record, two forms

The page is added by a single record inheriting
`l10n_ec_account_edi.view_move_form`. The liquidation form is a primary
view on `account.view_move_form`, and sibling extensions on that base
compose into it (the liquidation view itself already retargets nodes from
sibling extensions, e.g. `l10n_ec_electronic_authorization` and the
`l10n_ec_additional_information` page). A second record on the
liquidation view would render the page twice. The suite pins the page
count at one in both composed forms.

## IVA rows are derived, never assumed

`detalleImpuesto` needs a Tabla 17 percentage code the leg does not store,
so the IVA rate is derived from the leg's own amounts
(`iva_amount / taxed_base`) and mapped to the 0/12/14/15 codes. An
unrecognized rate, a taxed IVA without a base, and any ICE amount refuse
the emission with the entry and the valid codes named. The no-object
(`6`) and exempt (`7`) rows come straight from their buckets.

## ATS: total only

The collector override adds `totbasesImpReemb` (sum of `base_amount`) to
`_l10n_ec_compras_amounts` and leaves the document's own buckets intact,
mirroring Frappe's `collect_purchase`. It is added only when the move
holds legs, so ordinary rows stay byte-identical. Filing the total (and
the `reembolsos` detail rows) still needs the `l10n_ec_ats` builder to
emit it: that module withholds both as out of v1 scope, and a withheld
key present in a row is a generation refusal, not silent data loss. See
ROADMAP.
