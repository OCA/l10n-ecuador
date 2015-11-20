# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    "name" : "Ecuador - SRI - Retenciones",
    "version" : "1.0",
    "author" : "Comunidad Odoo Ecuador",
    'website' : '',
    "category" : "Tools",
    "description": """
SRI - Retenciones.
============================================

    * Implementa el registro del documento de retenciones.
        * Permite agregar el número de la retención.
        * Permite agregar la autorización de la retención.
        * Autorizaciones propias y de terceros.

""",
    'depends' : ['account',
                 'l10n_ec_sri_ats_16',
                 'l10n_ec_sri_autorizaciones',
                 ],
    'data' : [
        'views/invoice_views.xml',
        ],
    'demo': [],
    'auto_install': False,
    'installable': True,
    'images': [],
}
