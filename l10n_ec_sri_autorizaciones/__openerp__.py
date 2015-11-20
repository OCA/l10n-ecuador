# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    "name" : "Ecuador - SRI - Autorizaciones",
    "version" : "1.0",
    "author" : "Comunidad Odoo Ecuador",
    'website' : '',
    "category" : "Tools",
    "description": """
SRI - Autorizaciones.
============================================

    * Se implementa el manejo de autorizaciones del SRI.
        * Autorizaciones propias.
        * Autorizaciones de terceros.

""",
    'depends' : ['account',
                 'l10n_ec_sri_ats_16',
                 ],
    'data' : [
        'views/invoice_views.xml',
        'views/autorizacion_views.xml',
        'views/lineaautorizacion_views.xml',
        ],
    'demo': [],
    'auto_install': False,
    'installable': True,
    'images': [],
}
