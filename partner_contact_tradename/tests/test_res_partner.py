# Copyright 2022: PBox (<https://www.pupilabox.net.ec>)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests import common


class TestResPartner(common.TransactionCase):
    def setUp(self):
        super(TestResPartner, self).setUp()
        self.partner_admin = self.env.ref("base.partner_admin")
        self.partner_admin.write({"tradename": "PupilaBox"})

    @classmethod
    def setUpClass(cls):
        super(TestResPartner, cls).setUpClass()

        cls.partner = cls.env["res.partner"].create(
            {
                "name": "Test partner",
                "vat": "EC1103410021",
                "tradename": "La Fabrica Lógica",
            }
        )

    def test_field_tradename(self):
        """Test field trademark created"""
        self.assertEqual(self.partner.tradename, "La Fabrica Lógica")

    def test_name_search(self):
        """Test name search and partner field"""
        names = self.partner_admin.name_search(name="Pup")
        self.assertEqual(self.partner_admin.tradename, "PupilaBox")
        self.assertEqual(names[0][0] == self.partner_admin.id, True)
