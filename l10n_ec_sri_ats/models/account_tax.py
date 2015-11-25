# -*- coding: utf-8 -*-
from openerp import models, fields


class AccountTax(models.Model):
    _inherit = 'account.tax'

    sustento_id = fields.Many2one('l10n_ec_sri_ats.sustento',
                                  ondelete='restrict',
                                  string="Sustento tributario")
