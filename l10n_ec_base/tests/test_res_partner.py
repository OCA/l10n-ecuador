from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.base.tests.common import TransactionCaseWithUserDemo


@tagged("post_install", "-at_install")
class TestResPartner(TransactionCaseWithUserDemo):
    def test_consumer_final(self):
        partner_final = self.env.ref("l10n_ec.ec_final_consumer")
        other_partner = self.env["res.partner"].create({"name": "OTRO CLIENTE"})
        # intentar modificar datos con usuario admin, no debe lanzar error
        partner_final.sudo().write({"name": "NUEVO CLIENTE"})
        # intentar modificar datos con usuario normal, debe lanzar error
        with self.assertRaises(UserError):
            partner_final.with_user(self.user_demo).write({"name": "NUEVO CLIENTE"})
        # Eliminacion de consumidor final y partner normal
        with self.assertRaises(UserError):
            partner_final.unlink()
        other_partner.unlink()
