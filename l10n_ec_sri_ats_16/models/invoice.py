# -*- coding: utf-8 -*-
from openerp import models, fields

class AccountInvoice(models.Model):
    _inherit = ['account.invoice']
    
    comprobante_id = fields.Many2one('l10n_ec_sri_ats_16.comprobante',
                                      string='Tipo de comprobante')