# -*- coding: utf-8 -*-
from openerp import models, fields

class AccountJournal(models.Model):
    _inherit = ['account.journal']
    
    tipopago_id = fields.Many2one('l10n_ec_sri_ats_16.tipopago',
                                  string='Tipo de pago principal')
    formapago_id = fields.Many2one('l10n_ec_sri_ats_16.formapago',
                                   string='Forma de pago principal')