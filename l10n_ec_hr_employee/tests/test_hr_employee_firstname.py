# Copyright (C) 2014 Savoir-faire Linux. All Rights Reserved.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo.tests import TransactionCase


class TestEmployeeFirstname(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee_model = cls.env["hr.employee"]

        # Create 3 employees to concatenate the firstname and lastname
        # in name_related
        cls.employee1_id = cls.employee_model.create(
            {"firstname": "Jan", "lastname": "Van-Eyck"}
        )
        cls.employee2_id = cls.employee_model.create(
            {"firstname": "Jean-Pierre", "lastname": "Carnaud"}
        )
        cls.employee3_id = cls.employee_model.create(
            {"firstname": "Famke", "lastname": "Jenssens"}
        )

        # Create 3 employees for split the name_related to
        # firstname and lastname
        cls.employee10_id = cls.employee_model.create({"name": " Van-Eyck Jan"})
        cls.employee20_id = cls.employee_model.create({"name": "Carnaud Jean-Pierre"})
        cls.employee30_id = cls.employee_model.create({"name": "JenssensFamke"})

    def test_get_name(self):
        """Validate the _get_name method is concatenating the firstname and lastname."""
        self.assertEqual(self.employee1_id.name, "Van-Eyck Jan")
        self.assertEqual(self.employee2_id.name, "Carnaud Jean-Pierre")
        self.assertEqual(self.employee3_id.name, "Jenssens Famke")

    def test_auto_init_name(self):
        """Validate the create method if the name is split in firstname and lastname."""
        self.assertEqual(self.employee10_id.firstname, "Jan")
        self.assertEqual(self.employee10_id.lastname, "Van-Eyck")

        self.assertEqual(self.employee20_id.firstname, "Jean-Pierre")
        self.assertEqual(self.employee20_id.lastname, "Carnaud")

        self.assertEqual(self.employee30_id.firstname, " ")
        self.assertEqual(self.employee30_id.lastname, "JenssensFamke")

    def test_change_name(self):
        self.employee1_id.write({"name": "Carnaud-Eyck Jean-Pierre"})
        self.employee1_id.invalidate_recordset()

        self.assertEqual(self.employee1_id.firstname, "Jean-Pierre")
        self.assertEqual(self.employee1_id.lastname, "Carnaud-Eyck")

    def test_change_name_with_space(self):
        self.employee1_id.write({"name": "  Carnaud-Eyck  Jean-Pierre"})
        self.employee1_id.invalidate_recordset()

        self.assertEqual(self.employee1_id.firstname, "Jean-Pierre")
        self.assertEqual(self.employee1_id.lastname, "Carnaud-Eyck")

    def test_change_firstname(self):
        self.employee1_id.write({"firstname": "Jean-Pierre"})
        self.employee1_id.invalidate_recordset()

        self.assertEqual(self.employee1_id.name, "Van-Eyck Jean-Pierre")

    def test_change_lastname(self):
        self.employee1_id.write({"lastname": "Carnaud"})
        self.employee1_id.invalidate_recordset()

        self.assertEqual(self.employee1_id.name, "Carnaud Jan")

    def test_change_firstname_and_lastname(self):
        self.employee1_id.write({"firstname": "Jean-Pierre", "lastname": "Carnaud"})
        self.employee1_id.invalidate_recordset()

        self.assertEqual(self.employee1_id.name, "Carnaud Jean-Pierre")
