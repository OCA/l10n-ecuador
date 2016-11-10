# -*- coding: utf-8 -*-
from openerp import models, fields


class Canton(models.Model):
    _name = 'l10n_ec_ote.canton'

    state_id = fields.Many2one(
        'res.country.state', ondelete='restrict', string="State", )
    name = fields.Char(string="Canton", )
    code = fields.Char(string="Code", )


class Parish(models.Model):
    _name = 'l10n_ec_ote.parish'

    canton_id = fields.Many2one(
        'l10n_ec_ote.canton', ondelete='restrict', string="Canton", )
    name = fields.Char(string="Parish", )
    code = fields.Char(string="Code", )
