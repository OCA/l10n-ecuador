# -*- coding: utf-8 -*-
from openerp import models, fields


class ResCompany(models.Model):
    _inherit = 'res.company'

    establecimientos = fields.Char(string='Establecimientos activos',
        help="""Ingrese el número de establecimientos activos
                inscritos en el R.U.C.""",
        size=3)
