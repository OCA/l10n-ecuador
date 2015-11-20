# -*- coding: utf-8 -*-
from openerp import models, fields

class FiscalPosition(models.Model):
    _inherit = 'account.fiscal.position'
    
    identificacion_id = fields.Many2one('l10n_ec_sri_ats_16.identificacion',
                                        ondelete='restrict',
                                        string="Tipo de documento")
    persona_id = fields.Many2one('l10n_ec_sri_ats_16.persona',
                                 ondelete='restrict',
                                 string="Tipo de persona")