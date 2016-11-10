# -*- coding: utf-8 -*-
from openerp import models, fields, api


class ResCompany(models.Model):
    _inherit = 'res.company'

    @api.multi
    @api.onchange("canton_id")
    def _onchange_canton_id(self):
        for r in self:
            if not r.city:
                r.city = r.canton_id.name.capitalize() or ''

    country_id = fields.Many2one(default="base.ec", )
    canton_id = fields.Many2one(
        'l10n_ec_ote.canton', ondelete='restrict', string="Canton",
        related="partner_id.canton_id", )
    parish_id = fields.Many2one(
        'l10n_ec_ote.parish', ondelete='restrict', string="Parish",
        related="partner_id.parish_id", )
