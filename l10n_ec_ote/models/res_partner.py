# -*- coding: utf-8 -*-
from openerp import models, fields


class ResPartner(models.Model):
    _inherit = 'res.partner'

    country_id = fields.Many2one(default="base.ec", )
    canton_id = fields.Many2one('l10n_ec_ote.canton',
                                ondelete='restrict',
                                string="Cantón", )
    parroquia_id = fields.Many2one('l10n_ec_ote.parroquia',
                                   ondelete='restrict',
                                   string="Parroquia", )
