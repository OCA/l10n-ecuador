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
    es_publica = fields.Boolean('¿Es una Institución pública')
    obligada_contabilidad = fields.Boolean('¿Obligada a llevar contabilidad')
