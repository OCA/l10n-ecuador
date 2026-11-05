Nothing to configure.

The module requires `l10n_ec_account_edi` to be installed. The only user
interface is the import wizard, reachable from **Invoicing ‣ SRI ‣ Import
Supplier XML**. The wizard defaults (purchase journal, expense account)
can be changed per import; the bill stays draft for review.

The access-key door queries the SRI authorization service at import
time, so it needs the SRI host to be reachable from the Odoo container.
The file door works fully offline.
