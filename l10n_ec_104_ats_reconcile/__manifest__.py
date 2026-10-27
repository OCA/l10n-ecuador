{
    "name": "Ecuadorian Form 104 vs ATS Reconciliation",
    "summary": "Reconcile the 104 aggregates against the ATS blocks per period",
    "category": "Account",
    "countries": ["ec"],
    "author": "Odoo Community Association (OCA)",
    "maintainers": ["cormaza"],
    "website": "https://github.com/OCA/l10n-ecuador",
    "license": "AGPL-3",
    "version": "19.0.1.0.0",
    "depends": ["l10n_ec_104", "l10n_ec_ats"],
    "data": [
        "security/ir.model.access.csv",
        "views/l10n_ec_104_ats_reconcile_views.xml",
    ],
    "installable": True,
    "auto_install": False,
}
