# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    "name" : "Ecuador - SRI - Anexo Transaccional",
    "version" : "1.0",
    "author" : "Comunidad Odoo Ecuador",
    'website' : '',
    "category" : "Localization/Account Charts",
    "description": """
SRI - Anexo transaccional.
============================================

    * Se crean los modelos requeridos para generar el ATS.
        * Tipos de comprobante.
        * Sustentos tributarios.
        * Tipos de documento de identificación.
        * Tipos de persona.
    * Se definen características especiales para el res.partner a través de su posición fiscal.
        * Tipo de documento.
        * Tipo de persona.

""",
    'depends' : ['account',
                 'account_accountant',
                 ],
    'data' : [
        'views/payment_views.xml',
        'views/comprobante_views.xml',
        'views/persona_views.xml',
        'views/identificacion_views.xml',
        'views/sustento_views.xml',
        'views/partner_views.xml',
        'views/company_views.xml',
        'views/account_tax_views.xml',
        'views/invoice_views.xml',
        'views/fiscal_position_views.xml',
        'data/l10n_ec_sri_ats_16.tipopago.csv',
        'data/l10n_ec_sri_ats_16.formapago.csv',
        'data/l10n_ec_sri_ats_16.comprobante.csv',
        'data/l10n_ec_sri_ats_16.sustento.csv',
        'data/l10n_ec_sri_ats_16.identificacion.csv',
        'data/l10n_ec_sri_ats_16.persona.csv',
        ],
    'demo': [],
    'auto_install': False,
    'installable': True,
    'images': [],
}
