{
    "name": "Payphone Payment Provider",
    "category": "Accounting/Payment Acquirers",
    "summary": "Payphone Payment Provider",
    "version": "17.0.1.0.0",
    "author": "Odoo Community Association (OCA), Carlos Lopez",
    "website": "https://github.com/OCA/l10n-ecuador",
    "license": "AGPL-3",
    "depends": [
        "payment",
    ],
    "external_dependencies": {
        "python": [],
    },
    "data": [
        "views/payment_provider_templates.xml",
        "data/payment_provider_data.xml",
        "views/payment_provider_views.xml",
    ],
    "installable": True,
    "post_init_hook": "post_init_hook",
    "uninstall_hook": "uninstall_hook",
}
