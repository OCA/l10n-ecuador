This module is the foundation of the SRI *Anexo Transaccional Simplificado*
(ATS) generation for Ecuadorian companies.

The 21 referential catalogs published by the SRI (`Catalogo_ATS.xls`) are
**effective-dated**: the VAT rate regimes of `Tabla 12` change over time, the
withholding codes of `Tabla 11` start on different dates, most payment methods
of `Tabla 13` expired on 2016-08-31, and `Tabla 3.10` spreads its 414 income
withholding concepts across 22 date eras. Odoo 19 has no way to express that:
`account.tax` carries no `fields.Date` at all, so a rate change is currently
modelled by duplicating the record and archiving it with ``active = False``,
which leaves the history implicit and unqueryable.

This module therefore ships `l10n.ec.temporal`, an abstract mixin that gives
effective dating to the catalog models built on it: a `[date_start, date_end]`
window that is inclusive of both endpoints, where a null `date_end` means
open-ended, plus the resolution and structural-check helpers the ATS generator
needs to prove that the catalog is complete.

On top of it sits the generator: collectors that turn `account.move` records
into the five blocks of an ATS document, a builder that renders those payloads
in the order `ats.xsd` declares, the business validators `ats.xsd` cannot
express, and the wizard that produces `AT{mmaaaa}.zip`. `DESIGN.md` maps every
element of the document to the record it comes from.