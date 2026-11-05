# Design

Two doors, one parser. The attached file and the access-key fetch meet
in `parse_supplier_xml` (`models/sri_xml.py`, pure Python, no Odoo
dependency): a bare `<factura>` or the `<autorizacion>` envelope the
SRI returns (`<comprobante>` as CDATA or single child, plus
`numeroAutorizacion` for traceability).

## Behavior ported from Frappe

The Frappe precedent (`frappe_l10n_ec`, `sri/voucher_data.py`,
`sri/received_invoice.py`, `ecuador_localization/received_xml.py`)
shapes every rule:

- facturas (`01`) only; anything else is refused, never guessed;
- RUC → supplier, created on first sight (name clash with another RUC
  is refused, never merged);
- one bill line per XML detail with the single matching purchase tax;
- dedupe by (supplier, SRI number);
- the bill stays DRAFT; posting is the reviewer's job;
- fail loud on missing RUC/clave/lines.

## Where Odoo diverges, deliberately

- **Tax match.** Frappe matches the company's own templates by exact
  tarifa. Odoo's chart carries one purchase tax per sustento, so the
  match is (exact tarifa + SRI `codigoPorcentaje` through
  `l10n_ec_xml_fe_code`: 0 = 0%, 2 = 12%, 4 = 15%, 5 = 5%, 8 = 8%).
  Zero candidates → refusal listing the available purchase taxes
  (unknown rate). Several → the unqualified goods-credit tax wins
  (`VAT 15% 510 01`); with no plain candidate (0%), the cost-like `02`
  tax wins, else chart order. Reclassification stays a draft-review
  step, never silent data.
- **Non-IVA lines.** Frappe leaves ICE/IRBPNR lines untaxed; here a line
  with impuestos but no IVA is refused (the manual path), because
  silently dropping a tax changes the payable.
- **Mixed rates.** One line mixing VAT rates is refused (rates listed).
  Different rates across lines are fine: each line carries its own tax.
- **Dedupe.** Frappe's (supplier, bill number) plus a second key where
  Odoo has one: `l10n_ec_electronic_authorization` (auth number, or the
  clave when the envelope carries no separate authorization).
- **Currency.** `DOLAR*` maps to the company currency; anything else is
  refused. A non-USD company is refused rather than converted, because
  the XML carries no exchange rate.
- **File wins.** When file and key both arrive, the file is imported:
  it is the document the supplier actually sent.

## SRI fetch

The key door reuses the EDI format's zeep client
(`_l10n_ec_get_edi_ws_client`, cel/celcer URLs) and the
`autorizacionComprobante(claveAccesoComprobante=...)` call from
`account_edi_document.py`, then unwraps the response the same way
(single or list `autorizacion`, message aggregation, `AUTORIZADO`
only). No certificate is needed: authorization is the public service.
The fetched XML is attached to the bill, like an uploaded file.

## Non-goals

- reembolsos (41s travel their own path): refused with the manual-path
  message;
- ICE/IRBPNR-only lines: refused, untouched scope;
- header-total reconciliation: the draft is the reconciliation surface;
- sustento classification: the bill stays draft for it.
