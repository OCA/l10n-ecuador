{
    "name": "Ecuadorian SRI Supplier XML Import",
    "summary": "Draft vendor bills from SRI factura XML (file or access key)",
    "category": "Account",
    "countries": ["ec"],
    "author": "Odoo Community Association (OCA)",
    "maintainers": ["cormaza"],
    "website": "https://github.com/OCA/l10n-ecuador",
    "license": "AGPL-3",
    "version": "19.0.1.0.0",
    "depends": ["l10n_ec_account_edi"],
    "data": [
        "security/ir.model.access.csv",
        "data/res_partner_category.xml",
        "views/l10n_ec_xml_import_views.xml",
    ],
    "installable": True,
    "auto_install": False,
}
