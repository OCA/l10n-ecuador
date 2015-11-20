# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    "name" : "Ecuador - Impuestos - Comercio Exterior",
    "version" : "1.0",
    "author" : "Comunidad Odoo Ecuador",
    'website' : '',
    "category" : "Localization/Account Charts",
    "description": """
Impuestos extras de comercio exterior.
========================================

    * Define las posiciones fiscales para relaciones con el exterior.

IMPORTANTE: Este módulo no funciona como una plantilla normal de Odoo, registra sus componentes directamente en la empresa matriz de la base de datos. Si desea una plantilla debe editar el código acorde a los modelos estandar, puede usar como ejemplo el módulo l10n_lu.
""",
    'depends' : ['account',
                 'l10n_ec_sri_16',
                 ],
    'data' : [
        'views/fiscal_position_views.xls',
        'data/account.fiscal.position.csv',
        ],
    'auto_install': False,
    'installable': True,
    'images': [],
}
