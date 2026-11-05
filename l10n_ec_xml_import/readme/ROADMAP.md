# Roadmap

Out of scope in v1, with rationale and a v2 proposal.

| Case | Why out of v1 | Evidence | v2 proposal |
|---|---|---|---|
| Credit/debit notes, withholdings, liquidation XMLs | Parser and mapper cover facturas (`01`) only | `parse_supplier_xml` refuses non-`factura` roots | One mapper per voucher kind behind the same wizard |
| reembolsos (41s) | Own document path with its own taxes | Refused with the manual-path message | Reembolso detail model + dedicated bill lines |
| ICE/IRBPNR-only lines | Untouched scope, no Odoo-side template in v1 | Refused with the manual-path message | Excise-tax mapping table + tests |
| Sustento defaulting | Buyer-side classification the XML cannot carry | Bill stays draft for review | Default from the supplier's tax support with an override |
| Header-total reconciliation | Rounding and discounts vary by emitter | The draft is the reconciliation surface | Tolerance check with a warning chatter message |
