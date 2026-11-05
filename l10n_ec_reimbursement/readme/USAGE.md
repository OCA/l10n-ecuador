Recording reimbursed vouchers:

On a vendor bill (**Invoicing ‣ Vendors ‣ Bills**) or a purchase
liquidation (**Invoicing ‣ Vendors ‣ Liquidation of Purchase**), the
**Reimbursements** tab lists one row per third-party voucher: the SRI
document code (Tabla 4, e.g. `01`), the original supplier's ID type
(Tabla 10) and number, the `001-001-000000001` voucher number, the
emission date, the authorization, and the amount buckets. All rows on one
document must share a single document code, and every row needs at least
one base above zero; both are refused with the document and the reason
named.

Evidence from the suite (`test_l10n_ec_reimbursement.py`): a posted 03
liquidation with one `01` leg renders

```xml
<infoLiquidacionCompra>
  ...
  <codDocReembolso>01</codDocReembolso>
  <totalComprobantesReembolso>1.00</totalComprobantesReembolso>
  <totalBaseImponibleReembolso>100.00</totalBaseImponibleReembolso>
  <totalImpuestoReembolso>15.00</totalImpuestoReembolso>
  ...
</infoLiquidacionCompra>
<detalles>...</detalles>
<reembolsos>
  <reembolsoDetalle>
    <tipoIdentificacionProveedorReembolso>04</tipoIdentificacionProveedorReembolso>
    <identificacionProveedorReembolso>1790012345001</identificacionProveedorReembolso>
    <tipoProveedorReembolso>01</tipoProveedorReembolso>
    <codDocReembolso>01</codDocReembolso>
    <estabDocReembolso>001</estabDocReembolso>
    <ptoEmiDocReembolso>002</ptoEmiDocReembolso>
    <secuencialDocReembolso>000000003</secuencialDocReembolso>
    <fechaEmisionDocReembolso>04/03/2026</fechaEmisionDocReembolso>
    <numeroautorizacionDocReemb>1111111111111111111111111111111111111111111111111</numeroautorizacionDocReemb>
    <detalleImpuestos>
      <detalleImpuesto>
        <codigo>2</codigo>
        <codigoPorcentaje>4</codigoPorcentaje>
        <tarifa>15.00</tarifa>
        <baseImponibleReembolso>100.00</baseImponibleReembolso>
        <impuestoReembolso>15.00</impuestoReembolso>
      </detalleImpuesto>
    </detalleImpuestos>
  </reembolsoDetalle>
</reembolsos>
```

The same legs on a vendor bill render the identical block inside factura
01, and the ATS `compras` row for the document carries
`totbasesImpReemb` with the sum of the leg bases while the document's own
base buckets stay untouched.

Limits: legs carrying ICE refuse the emission (no tariff-code source in
v1), and an IVA rate outside the 0/12/14/15 codes refuses it as well
rather than filing an invented percentage.
