This module is the foundation of the SRI *Anexo Transaccional Simplificado*
(ATS) generation for Ecuadorian companies.

The 21 referential catalogs published by the SRI (`Catalogo_ATS.xls`) are
**effective-dated**: the VAT rate regimes of `Tabla 12` change over time, the
withholding codes of `Tabla 11` start on different dates, most payment methods
of `Tabla 13` expired on 2016-08-31, and `Tabla 3.10` spreads its 162 income
withholding concepts across 29 date eras. Odoo 19 has no way to express that:
`account.tax` carries no `fields.Date` at all, so a rate change is currently
modelled by duplicating the record and archiving it with ``active = False``,
which leaves the history implicit and unqueryable.

This module therefore introduces `l10n.ec.temporal`, an abstract mixin that
gives effective dating to the catalog models it will host: a
`[date_start, date_end]` window that is inclusive of both endpoints, where a
null `date_end` means open-ended, plus the resolution and structural-check
helpers the ATS generator needs to prove that the catalog is complete.