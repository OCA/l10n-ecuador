# -*- coding: utf-8 -*-
from openerp import models, fields


class Sustento(models.Model):
    _name = 'l10n_ec_sri_ats.sustento'

    name = fields.Char('Sustento Tributario')
    code = fields.Char('Código', size=2)
    active = fields.Boolean('Activo')
    description = fields.Char('Descripción')
    comprobante_ids = fields.Many2many('l10n_ec_sri_ats.comprobante',
                        'sustento_comprobante_relacion',
                        'sustento_ids',
                        'comprobante_ids',
                        string="Comprobantes",
                        help="""Seleccione los comprobantes con los cuales es
                        posible utilizar el presente sustento tributario.""")
