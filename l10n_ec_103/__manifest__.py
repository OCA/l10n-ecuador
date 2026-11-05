{
    "name": "Ecuadorian SRI Form 103 (Income Withholding)",
    "summary": "Prefill and traceability for the monthly withholding return",
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
        "views/l10n_ec_103_generate_views.xml",
    ],
    "installable": True,
    "auto_install": False,
}
