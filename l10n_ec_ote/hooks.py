import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger("l10n_ec_ote")


def pre_install_hook(cr):
    env = api.Environment(cr, SUPERUSER_ID, {})

    ec_provinces = env["res.country.state"].search(
        [("country_id", "=", env.ref("base.ec").id)]
    )

    if len(ec_provinces):
        _logger.warning("This odoo installation has already provinces set for Ecuador")
