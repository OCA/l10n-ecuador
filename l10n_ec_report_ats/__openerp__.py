# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    "name" : "Reporte - SRI - Anexo Transaccional",
    "version" : "1.0",
    "author" : "Comunidad Odoo Ecuador",
    'website' : '',
    "category" : "Reports",
    "description": """
SRI - Anexo transaccional.
============================================

    * Generación del Anexo Transaccional en xml

""",
    'depends' : ['account',
                 'l10n_ec_sri_ats_16',
                 ],
    'data' : [
        'views/ats_views.xml',
        'views/partner_views.xml',
        'views/journal_views.xml',
        'views/fiscal_position_views.xml',
        ],
    'demo': [],
    'auto_install': False,
    'installable': True,
    'images': [],
}
