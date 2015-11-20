# -*- coding: utf-8 -*-
from openerp import models, fields

class FiscalPosition(models.Model):
    _inherit = 'account.fiscal.position'
    
    dobletributacion = fields.Boolean('Aplica convenio de doble tributación')