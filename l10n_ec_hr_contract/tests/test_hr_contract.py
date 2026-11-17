# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase


class TestHrContract(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env["hr.employee"].create(
            {"firstname": "Jan", "lastname": "Van-Eyck"}
        )
        cls.version = cls.employee.version_id
        cls.today = fields.Date.context_today(cls.version)

    def test_state_draft_without_start_date(self):
        self.assertEqual(self.version.state, "draft")

    def test_state_trial_after_start(self):
        self.version.contract_date_start = self.today
        self.version.base_trial_days = 90
        self.version.invalidate_recordset()
        self.assertEqual(self.version.state, "trial")

    def test_trial_date_end_computed_from_start(self):
        self.version.write(
            {
                "contract_date_start": "2026-01-01",
                "base_trial_days": 30,
            }
        )
        self.assertEqual(
            fields.Date.to_string(self.version.trial_date_end), "2026-01-31"
        )

    def test_state_contract_ending_within_30_days(self):
        self.version.write(
            {
                "contract_date_start": self.today - timedelta(days=200),
                "trial_date_end": self.today - timedelta(days=100),
                "contract_date_end": self.today + timedelta(days=5),
            }
        )
        self.assertEqual(self.version.state, "contract_ending")

    def test_state_pending_done_after_end_date(self):
        self.version.write(
            {
                "contract_date_start": self.today - timedelta(days=200),
                "trial_date_end": self.today - timedelta(days=100),
                "contract_date_end": self.today - timedelta(days=1),
            }
        )
        self.assertEqual(self.version.state, "pending_done")

    def test_state_open_without_trial_or_end(self):
        self.version.write(
            {
                "contract_date_start": self.today - timedelta(days=200),
                "trial_date_end": self.today - timedelta(days=100),
                "contract_date_end": False,
            }
        )
        self.assertEqual(self.version.state, "open")

    def test_age_days(self):
        self.version.write(
            {
                "contract_date_start": self.today - timedelta(days=10),
                "contract_date_end": False,
            }
        )
        self.assertEqual(self.version.age_days, 10)

    def test_end_trial_sets_trial_date_to_today(self):
        self.version.write(
            {
                "contract_date_start": self.today,
                "base_trial_days": 90,
            }
        )
        self.version.action_end_trial()
        self.assertEqual(self.version.trial_date_end, self.today)
