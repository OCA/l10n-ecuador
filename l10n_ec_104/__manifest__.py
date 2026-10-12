{
    "name": "Ecuadorian SRI Form 104 (IVA)",
    "summary": "Prefill and traceability for the monthly IVA return",
    "category": "Account",
    "countries": ["ec"],
    "author": "Odoo Community Association (OCA)",
    "maintainers": ["cormaza"],
    "website": "https://github.com/OCA/l10n-ecuador",
    "license": "AGPL-3",
    "version": "19.0.1.0.0",
    "depends": ["l10n_ec_base", "account"],
    "data": [
        "security/ir.model.access.csv",
        "views/l10n_ec_104_generate_views.xml",
    ],
    "installable": True,
    "auto_install": False,
}
