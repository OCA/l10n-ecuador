# -*- coding: utf-8 -*-
{
    'name': "O.T.E. - Ecuador",

    'summary': """Datos de provincias, cantones y parroquias de Ecuador.""",

    'description': """
Organizacion territorial del Ecuador.
=================================================
    * Introduce las modificaciones en res.partner e ingresa la información geopolítica de Ecuador.
        * Se ingresan las provincias del Ecuador en res.state.
        * Se crea el modelo 'canton' y se ingresan los cantones del Ecuador.
        * Se crea el modelo 'parroquia' y se ingresan las parroquias del Ecuador.
    * PENDIENTES.
        * Asignar el cantón padre a las parroquias.
    """,

    'author': 'Comunidad de Odoo Ecuador',
    'website': '',

    'category': 'Tools',
    'version': '0.02',

    # any module necessary for this one to work correctly
    'depends': [
        'base',
    ],

    # always loaded 
    'data': [
        'views/partner_views.xml',
        'data/res.country.state.csv',
        'data/l10n_ec_ote.canton.csv',
        'data/l10n_ec_ote.parroquia.csv',
    ],
    # only loaded in demonstration mode
    'demo': [
    ],
}
