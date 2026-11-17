This module creates draft vendor bills from Ecuadorian SRI supplier
factura (`01`) XML through one wizard with two doors: attach the XML file
the supplier sent, or type its 49-digit access key and let the wizard
fetch the authorized XML from the SRI `autorizacionComprobante` service.
Both doors feed the same parser, the same supplier resolution (RUC,
created under Imported Suppliers on first sight), the same per-line VAT
mapping by exact rate, and the same dedupe (supplier + SRI number, plus
the authorization key).
