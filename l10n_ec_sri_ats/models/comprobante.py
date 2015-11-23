# -*- coding: utf-8 -*-
from openerp import models, fields


class Comprobante(models.Model):
    _name = 'l10n_ec_sri_ats.comprobante'

    name = fields.Char('Comprobantes autorizados')
    code = fields.Char('Código', size=2)
    active = fields.Boolean('Activo')
    sustento_ids = fields.Many2many('l10n_ec_sri_ats.sustento',
                                    'sustento_comprobante_relacion',
                                    'comprobante_ids',
                                    'sustento_ids',
                                    string="Sustentos aplicables")
