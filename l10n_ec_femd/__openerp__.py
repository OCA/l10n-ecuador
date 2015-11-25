# -*- coding: utf-8 -*-
{
    'name': "Flujo de Efectivo (Directo) - Ecuador",
    'summary': """Clasifica cobros y pagos para el Flujo de Efectivo.""",
    'version': '9.0.1.0.0',
    'author': "Fabrica de Software Libre,Odoo Community Association (OCA)",
    'maintainer': 'Fabrica de Software Libre',
    'website': 'http://www.libre.ec',
    'license': 'AGPL-3',
    'category': 'Account',
    'depends': [
        'base',
        'account',
    ],
    'data': [
        'views/payment.xml',
    ],
    'demo': [],
    'test': [],
    'installable': True,
}
