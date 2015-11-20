# -*- coding: utf-8 -*-
from openerp import models, fields, api, exceptions, _

class Partner(models.Model):
    _inherit = 'res.partner'

    @api.one
    @api.constrains('vat')
    def _check_vat(self):
        if self.vat != '13':
            raise exceptions.Warning("El R.U.C. debe tener 13 digitos") 

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4: