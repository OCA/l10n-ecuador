# -*- coding: utf-8 -*-
{
    'name': "Ecuador - Niif Pymes - Base",
    'summary': """Agrega el plan de cuentas de la Supercias.""",
    'version': '9.0.1.0.0',
    'author': "Fabrica de Software Libre,Odoo Community Association (OCA)",
    'maintainer': 'Fabrica de Software Libre',
    'website': 'http://www.libre.ec',
    'license': 'AGPL-3',
    'category': 'Localization',
    'depends': [
        'base',
        'account',
    ],
    'data': [
        'data/account_chart_template.xml',
        'data/account.account.template.csv',
        'data/account_chart_template.yml',
    ],
    'demo': [],
    'test': [],
    'installable': True,
}
