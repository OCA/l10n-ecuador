# -*- coding: utf-8 -*-
from openerp import models, fields

class Payment(models.Model):
    _inherit = 'account.payment'
    
    tipopago_id = fields.Many2one('l10n_ec_sri_ats_16.tipopago',
                                      string='Tipo de pago')
    formapago_id = fields.Many2one('l10n_ec_sri_ats_16.formapago',
                                      string='Forma de pago')
# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
