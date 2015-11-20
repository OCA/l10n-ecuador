# -*- coding: utf-8 -*-
from openerp import models, fields

class Partner(models.Model):
    _inherit = 'res.partner'
    
    parterel = fields.Boolean(string="¿Es parte relacionada?", copy=False)
            
# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
