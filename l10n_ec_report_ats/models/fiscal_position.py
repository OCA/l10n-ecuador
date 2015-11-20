# -*- coding: utf-8 -*-
from openerp import models, fields

class FiscalPosition(models.Model):
    _inherit = 'account.fiscal.position'
    
    tipopago_id = fields.Many2one('l10n_ec_sri_ats_16.tipopago',
                                      string='Tipo de pago')