{
    "name": "Electronic Ecuadorian Localization",
    "summary": "Electronic data interchange adapted Ecuadorian localization",
    "category": "Account",
    "author": "Odoo Community Association (OCA), "
    "Renan Nazate, Gabriel, Leonardo, Yazber Romero",
    "website": "https://github.com/OCA/l10n-ecuador",
    "license": "AGPL-3",
    "version": "15.0.1.0.0",
    "depends": ["account", "account_edi", "l10n_ec", "l10n_ec_base"],
    "external_dependencies": {
        "python": ["cryptography==36.0.0", "xmlsig==0.1.9", "xades==0.2.4", "zeep"]
    },
    "data": [
        "security/ir.model.access.csv",
        "data/edi_format_data.xml",
        "data/edi_templates/edi_info_tributaria_data.xml",
        "data/edi_templates/edi_invoice.xml",
        "report/edi_report_templates.xml",
        "report/report_edi_invoice.xml",
        "report/report_invoice.xml",
        "views/sri_key_type_view.xml",
        "views/menu_root.xml",
        "views/account_move_view.xml",
        "views/res_config_settings_view.xml",
        "views/account_edi_document_view.xml",
    ],
    "assets": {
        "web.report_assets_common": [
            "l10n_ec_account_edi/static/src/scss/report_layout.scss"
        ],
    },
    "installable": True,
    "auto_install": False,
}
