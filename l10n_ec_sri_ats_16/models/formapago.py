# -*- coding: utf-8 -*-
from openerp import models, fields

class FormaPago(models.Model):
    _name = 'l10n_ec_sri_ats_16.formapago'

    name = fields.Char('Forma de pago')
    code = fields.Char('Código', size=2)