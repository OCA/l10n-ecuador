{
    "name": "Electronic Ecuadorian Localization",
    "summary": "Electronic data interchange adapted Ecuadorian localization",
    "category": "Account",
    "author": "Odoo Community Association (OCA), "
    "Carlos Lopez, Renan Nazate, Yazber Romero, Luis Romero, Jorge Quiguango",
    "website": "https://github.com/OCA/l10n-ecuador",
    "license": "AGPL-3",
    "version": "19.0.1.0.0",
    "depends": ["account", "account_edi", "l10n_ec", "l10n_ec_base"],
    "external_dependencies": {
        "python": [
            # Floor >=42: sri.key.type._l10n_ec_cert_date relies on the aware
            # not_valid_before_utc/not_valid_after_utc attributes (naive ones
            # deprecated since 42).
            "cryptography>=42",
            # Coupled floor: cryptography>=42 pulls 42+ (CI installs 50.x)
            # while images still ship pyOpenSSL 21, whose
            # OpenSSL/crypto.py reads _lib.GEN_EMAIL, an attribute removed
            # from cryptography 42+. Without this floor the server cannot
            # even load base/web. Odoo itself pairs them the same way
            # (requirements.txt: cryptography==42.0.8 with
            # pyopenssl==24.1.0 on py>=3.12).
            "pyopenssl>=24.1.0",
            # Coupled floor: odoo/addons/base/models/ir_mail_server.py imports
            # urllib3.contrib.pyopenssl, whose 1.26.x line imports
            # cryptography.hazmat.backends.openssl.x509._Certificate, a
            # namespace removed in cryptography 50 (CI installs 50.0.2).
            # Odoo itself pairs urllib3==2.0.7 with that modern stack.
            "urllib3>=2.0.7",
            # Floor for the xmlsig API surface used in action_sign.
            "xmlsig>=0.1.9",
            # Keep pinned: 1-arg XAdESContext(...) not verified on 1.0.0.
            "xades==0.2.4",
            # Kept unpinned: no tested == version known, do not invent one.
            "zeep",
        ]
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
        "data/cron_check_certificate.xml",
        "data/cron_check_unauthorized_electronic_document.xml",
        "data/email_template_edi_invoice.xml",
        "data/email_template_certificate_notify.xml",
        "data/email_template_unauthorized_notify.xml",
        "report/edi_report_templates.xml",
        "report/report_edi_invoice.xml",
        "report/report_edi_liquidation.xml",
        "report/report_edi_credit_note.xml",
        "report/report_invoice.xml",
        "report/report_edi_debit_note.xml",
        "wizard/account_move_reversal_view.xml",
        "views/sri_key_type_view.xml",
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
