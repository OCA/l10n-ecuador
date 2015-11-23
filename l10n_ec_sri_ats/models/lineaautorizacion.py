# -*- coding: utf-8 -*-
from openerp import models, fields


class LineaAutorizacion(models.Model):
    _name = 'l10n_ec_sri_ats.lineaautorizacion'

    comprobante_id = fields.Many2one(
        'l10n_ec_sri_ats.comprobante', string="Comprobante")
    secuencia_inicial = fields.Char('Secuencia inicial')
    secuencia_final = fields.Char('Secuencia final')
    secuencia_siguiente = fields.Char(
        'Secuencia siguiente',
        help="""Ingrese el número de documento que
                continua en la secuencia""")
    autorizacion_id = fields.Many2one(
        'l10n_ec_sri_ats.autorizacion', string='Autorización')
