# -*- coding: utf-8 -*-
from openerp import models, fields


class ResPartner(models.Model):
    _inherit = 'res.partner'

    parterel = fields.Boolean(string="¿Es parte relacionada?",
                              copy=False)
