from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models


class SriAts(models.Model):
    _name = "sri.ats"

    name = fields.Char(string="Name", compute="_compute_name", store=True)
    date_start = fields.Date(
        string="Start Date", default=lambda self: self._default_start_date()
    )
    date_end = fields.Date(
        string="End Date", default=lambda self: self._default_end_date()
    )
    xml_file = fields.Binary(string="XML File", readonly=True, store=True)
    file_name = fields.Char(
        string="File Name", readonly=True, store=True, compute="_compute_name"
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        default=lambda self: self.env.company,
        required=True,
    )
    sri_state = fields.Selection(
        [
            ("draft", "Draft"),
            ("done", "Done"),
        ],
        string="SRI State",
        default="draft",
        required=True,
    )

    @api.model
    def _default_start_date(self):
        today = date.today()
        first_day_last_month = today.replace(day=1) - relativedelta(months=1)
        return first_day_last_month

    @api.model
    def _default_end_date(self):
        today = date.today()
        first_day_this_month = today.replace(day=1)
        last_day_last_month = first_day_this_month - timedelta(days=1)
        return last_day_last_month

    @api.depends("date_start", "date_end")
    def _compute_name(self):
        for record in self:
            if record.date_start and record.date_end:
                record.file_name = "AT%s.xml" % (record.date_end.strftime("%Y%m"))
                record.name = "AT%s" % (record.date_end.strftime("%Y%m"))
            else:
                record.file_name = False
                record.name = False

    def action_draft(self):
        self.write({"sri_state": "draft"})

    def action_done(self):
        self.write({"sri_state": "done"})

    def action_load(self):
        print("Load ATS")
