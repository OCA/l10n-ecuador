from . import models
from . import wizard


def _10n_ec_withhold_post_init(env):
    env["account.chart.template"]._10n_ec_withhold_post_init()
