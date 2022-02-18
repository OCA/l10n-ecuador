# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

import logging

from odoo.tests import common

_logger = logging.getLogger("ote")


class TestResPartner(common.SingleTransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        _logger.setLevel(logging.INFO)

        cls.states = cls.env["res.country.state"].search(
            [("country_id", "=", cls.env.ref("base.ec").id)]
        )

        _logger.debug(
            "checking dbs %s %s",
            cls.env["res.country.state"].country_id,
            cls.env["l10n_ec_ote.canton"].state_id,
        )

        cls.cantons = cls.env["l10n_ec_ote.canton"].search([])
        cls.parish = cls.env["l10n_ec_ote.parish"].search([])

    def test_province_creation(self):
        _logger.debug("getting states %s", len(self.states))
        EC_STATES_NUM = 24

        self.assertTrue(len(self.states) == EC_STATES_NUM)

    def test_canton_creation(self):
        _logger.debug("getting canton %s", len(self.cantons))
        EC_CANTONS_NUM = 221

        self.assertTrue(len(self.cantons) == EC_CANTONS_NUM)

    def test_parish_creation(self):
        _logger.debug("getting parish %s", len(self.parish))
        EC_PARISH_NUM = 1259

        self.assertTrue(len(self.parish) == EC_PARISH_NUM)
