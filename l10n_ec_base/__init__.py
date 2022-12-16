from . import models
from . import wizard

from odoo import api, SUPERUSER_ID


def _l10n_ec_base_post_init(cr, registry):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env["account.chart.template"]._10n_ec_post_init()
