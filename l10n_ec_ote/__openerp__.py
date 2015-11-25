# -*- coding: utf-8 -*-
{
    'name': "O.T.E. - Ecuador",
    'summary': """Datos de provincias, cantones y parroquias de Ecuador.""",
    'version': '9.0.1.0.0',
    'author': "Fabrica de Software Libre,Odoo Community Association (OCA)",
    'maintainer': 'Fabrica de Software Libre',
    'website': 'http://www.libre.ec',
    'license': 'AGPL-3',
    'category': 'Tools',
    'depends': [
        'base',
    ],
    'data': [
        'views/res_partner.xml',
        'data/res.country.state.csv',
        'data/l10n_ec_ote.canton.csv',
        'data/l10n_ec_ote.parroquia.csv',
        'security/ir.model.access.csv',
    ],
    'demo': [],
    'test': [],
    'installable': True,
}
