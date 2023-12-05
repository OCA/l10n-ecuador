from . import models
from . import wizard


def _l10n_ec_base_post_init(env):
    env["account.chart.template"]._10n_ec_post_init()
