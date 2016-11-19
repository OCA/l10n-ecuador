# -*- coding: utf-8 -*-
from openerp import models, fields


class EcuadorConfigSettings(models.TransientModel):
    _name = 'l10n_ec_config.config.settings'
    _inherit = 'res.config.settings'

    module_l10n_ec_ote = fields.Boolean(
        "Use Ecuador's Geopolitical information on partners.", )
    module_l10n_ec = fields.Boolean(
        "Use SUPERCIAS's Chart of accounts.", )
