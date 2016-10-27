# -*- coding: utf-8 -*-
from openerp import models, fields, api


class ResPartner(models.Model):
    _inherit = 'res.partner'

    @api.onchange("canton_id")
    def _onchange_canton_id(self):
        self.city = self.canton_id.name or ""

    country_id = fields.Many2one(default="base.ec", )
    canton_id = fields.Many2one(
        'l10n_ec_ote.canton', ondelete='restrict', string="Canton", )
    parish_id = fields.Many2one(
        'l10n_ec_ote.parish', ondelete='restrict', string="Parish", )
