# -*- coding: utf-8 -*-
from openerp import models, fields

class AccountTax(models.Model):
    _inherit = 'account.tax'

    sustento_id = fields.Many2one('l10n_ec_sri_ats_16.sustento', ondelete='restrict', string="Sustento tributario")
            
# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
