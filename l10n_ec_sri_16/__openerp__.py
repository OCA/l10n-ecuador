# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    "name" : "Ecuador - SRI - Impuestos comunes",
    "version" : "1.0",
    "author" : "Comunidad Odoo Ecuador",
    'website' : '',
    "category" : "Localization/Account Charts",
    "description": """
Impuestos comunes para Ecuador.
============================================

    * Define los impuestos acorde al SRI.
        * I.V.A. en compras y ventas.
        * Retenciones del I.R.
        * Retenciones de I.V.A.
    * Define las posiciones fiscales basicas.
        * Para empresas sin relaciones comerciales fuera del país.
        * Para empresas sin partes relacionadas.
    * Registro contable de impuestos.
        * Los impuestos no se encuentran mapeados a cuentas contables específicas, por lo que debe realizar la configuración de manera manual o instalar el módulo l10n_ec_niif_sri.

IMPORTANTE: Este módulo no funciona como una plantilla normal de Odoo, registra sus componentes directamente en la empresa matriz de la base de datos. 

Si desea una plantilla debe editar el código acorde a los modelos estandar, puede usar como ejemplo el módulo l10n_lu. 

Usar una plantilla solo es necesario cuando desea usar el sistema en un entorno multi-compañías, caso contrario, este módulo le será útil tal y como ha sido desarrollado.
""",
    'depends' : ['account',
                 'l10n_ec_sri_ats_16',
                 ],
    'data' : [
        "data/103/account.account.tag.csv",
        "data/103/account.tax.group.csv",
        "data/103/account.tax.csv",
        "data/104/account.account.tag.csv",
        "data/104/account.tax.group.csv",
        "data/104/account.tax.csv",
        "data/101/account.account.tag.csv",
        "data/101/account.tax.group.csv",
        "data/101/account.tax.csv",
        "data/account.fiscal.position.csv",
        ],
    'demo': [],
    'auto_install': False,
    'installable': True,
    'images': [],
}
