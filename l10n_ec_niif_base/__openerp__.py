# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    "name" : "Ecuador - Niif Pymes - Base",
    "version" : "1.0",
    "author" : "Comunidad Odoo Ecuador",
    'website' : '',
    "category" : "Localization/Account Charts",
    "description": """
Cuentas contables comunes para NIIF Pymes.
===============================================

El módulo instala las cuentas del Plan de Cuentas publicado por la Superintendencia de compañías para las Pymes. Debido al nuevo módelo de cuentas de Odoo se crean solamente las cuentas del tipo "D" (detalle) del mencionado documento.

IMPORTANTE: Este módulo no funciona como una plantilla normal de Odoo, registra sus componentes directamente en la empresa matriz de la base de datos. 

Si desea una plantilla debe editar el código acorde a los modelos estandar, puede usar como ejemplo el módulo l10n_lu o l10n_si.

Usar una plantilla solo es necesario cuando desea usar el sistema en un entorno multi-compañías, caso contrario, este módulo le será útil tal y como ha sido desarrollado.
""",
    'depends' : ["account"],
    'data' : [
        'data/account_chart.xml',
        'data/account.account.csv',
        'data/account_chart_template.yml',
        ],
    'demo': [],
    'auto_install': False,
    'installable': True,
    'images': [],
}
