# -*- coding: utf-8 -*-
from openerp import models, fields


class ResCompany(models.Model):
    _inherit = 'res.company'

    establecimientos = fields.Char(
        string='Establecimientos activos', size=3,
        help="""Ingrese el número de establecimientos activos
                inscritos en el R.U.C.""")
    vat_ec = fields.Char('Idenfificación fiscal')
