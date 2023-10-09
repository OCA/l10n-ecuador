{
    "name": "Electronic Ecuadorian Localization",
    "summary": "Electronic data interchange adapted Ecuadorian localization",
    "category": "Account",
    "author": "Odoo Community Association (OCA), "
    "Carlos Lopez, Renan Nazate, Yazber Romero, Luis Romero, Jorge Quiguango",
    "website": "https://github.com/OCA/l10n-ecuador",
    "license": "AGPL-3",
    "version": "15.0.1.2.3",
    "depends": ["account", "account_edi", "l10n_ec", "l10n_ec_base"],
    "external_dependencies": {
        "python": ["cryptography==36.0.0", "xmlsig==0.1.9", "xades==0.2.4", "zeep"]
    },
    "data": [
        "security/ir.model.access.csv",
        "data/edi_format_data.xml",
        "data/edi_templates/edi_info_tributaria_data.xml",
        "data/edi_templates/edi_invoice.xml",
        "data/edi_templates/edi_liquidation.xml",
        "data/edi_templates/edi_credit_note.xml",
        "data/edi_templates/edi_debit_note.xml",
        "data/cron_send_email_electronic_documents.xml",
        "data/email_template_edi_invoice.xml",
        "report/edi_report_templates.xml",
        "report/report_edi_invoice.xml",
        "report/report_edi_liquidation.xml",
        "report/report_edi_credit_note.xml",
        "report/report_invoice.xml",
        "report/report_edi_debit_note.xml",
        "wizard/account_move_reversal_view.xml",
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
