{
    "name": "Sri Reports for Ecuadorian Localization",
    "summary": """SRI(Servicio de Rentas Internas)
                reports adapted in Ecuadorian localization""",
    "category": "Account",
    "countries": ["ec"],
    "author": "Odoo Community Association (OCA), Odoo-EC",
    "website": "https://github.com/OCA/l10n-ecuador",
    "license": "AGPL-3",
    "version": "17.0.1.0.1",
    "depends": ["l10n_ec_base", "l10n_ec_account_edi", "l10n_ec_withhold"],
    "data": [
        "security/ir.model.access.csv",
        "data/edi_sri.xml",
        "views/res_partner_view.xml",
        "views/menu_root.xml",
        "views/ats_sri_view.xml",
    ],
    "installable": True,
    "auto_install": False,
}
