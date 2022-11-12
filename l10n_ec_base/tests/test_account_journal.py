from odoo.exceptions import ValidationError
from odoo.tests import common


class TestModelA(common.TransactionCase):
    def test_some_action(self):
        record = self.env["account.journal"].create(
            {
                "name": "nametest",
                "type": "sale",
                "l10n_latam_use_documents": True,
                "code": "inv",
                "l10n_ec_entity": "001",
            }
        )
        self.assertEqual(record.name, "nametest")
        with self.assertRaises(ValidationError):
            record.write({"l10n_ec_entity": "abc"})
