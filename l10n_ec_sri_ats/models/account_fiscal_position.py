# -*- coding: utf-8 -*-
from openerp import models, fields


class AccountFiscalPosition(models.Model):
    _inherit = 'account.fiscal.position'

    identificacion_id = fields.Many2one('l10n_ec_sri_ats.identificacion',
                                        ondelete='restrict',
                                        string="Tipo de documento")
    persona_id = fields.Many2one('l10n_ec_sri_ats.persona',
                                 ondelete='restrict',
                                 string="Tipo de persona")
    es_gobierno = fields.Boolean('¿Es uan Institución Gubernamental')
    obligada_contabilidad = fields.Boolean('¿Está obligada a llevar contabilidad')
