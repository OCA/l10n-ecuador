# -*- coding: utf-8 -*-
from openerp import models, fields

class Company(models.Model):
    _inherit = 'res.company'
    
    establecimientos = fields.Char(string='Número de establecimientos', help="Ingrese el número de establecimientos activos inscritos en el R.U.C.", size=3)
            
# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
