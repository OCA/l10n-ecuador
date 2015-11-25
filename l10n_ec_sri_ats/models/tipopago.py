# -*- coding: utf-8 -*-
from openerp import models, fields


class TipoPago(models.Model):
    _name = 'l10n_ec_sri_ats.tipopago'

    name = fields.Char('Tipo de pago')
    code = fields.Char('Código', size=2)
