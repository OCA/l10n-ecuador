# -*- coding: utf-8 -*-
from openerp import models, fields


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    tipopago_id = fields.Many2one(
        'l10n_ec_sri_ats.tipopago', string='Tipo de pago')
    formapago_id = fields.Many2one(
        'l10n_ec_sri_ats.formapago', string='Forma de pago')
