# Copyright 2015 Michael Telahun Makonnen <mmakonnen@gmail.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError


class HrVersion(models.Model):
    _inherit = "hr.version"

    @api.depends("name", "employee_id")
    def _compute_display_name(self):
        for version in self:
            version.display_name = f"{version.name} - {version.employee_id.name or ''}"

    @api.depends("contract_date_start", "contract_date_end", "trial_date_end", "active")
    def _compute_state(self):
        today = fields.Date.context_today(self)
        trial_limit = today + relativedelta(days=10)
        contract_limit = today + relativedelta(days=30)
        for version in self:
            if not version.active:
                state = "done"
            elif not version.contract_date_start:
                state = "draft"
            elif version.contract_date_end and version.contract_date_end < today:
                state = "pending_done"
            elif (
                version.contract_date_end
                and version.contract_date_end <= contract_limit
            ):
                state = "contract_ending"
            elif version.trial_date_end and version.trial_date_end >= today:
                state = (
                    "trial_ending" if version.trial_date_end <= trial_limit else "trial"
                )
            else:
                state = "open"
            version.state = state

    @api.depends("contract_date_start", "contract_date_end")
    def _compute_age_days(self):
        today = fields.Date.context_today(self)
        for version in self:
            if not version.contract_date_start:
                version.age_days = 0
                continue
            end = version.contract_date_end or today
            version.age_days = (end - version.contract_date_start).days

    @api.model
    def _default_base_trial_days(self):
        return int(
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("l10n_ec_hr_contract.base_trial_days", 90)
        )

    @api.model
    def _default_wage_base_legal(self):
        return float(
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("l10n_ec_hr_contract.wage_base_legal", 375)
        )

    state = fields.Selection(
        [
            ("draft", "Borrador"),
            ("trial", "Pruebas"),
            ("trial_ending", "Terminando Pruebas"),
            ("open", "Abierto"),
            ("contract_ending", "Finalizando"),
            ("pending_done", "Pendiente de Cierre"),
            ("done", "Completado"),
        ],
        string="Estado",
        compute="_compute_state",
        store=True,
    )
    end_job_id = fields.Many2one(
        "hr.job",
        string="Job Position at End",
        readonly=True,
        help="Job title held when the contract ended.",
    )
    base_trial_days = fields.Integer(
        default=lambda self: self._default_base_trial_days(),
    )
    wage_base_legal = fields.Float(
        digits=(16, 2),
        default=lambda self: self._default_wage_base_legal(),
        required=True,
    )
    p_hipotecario = fields.Float(
        string="Prestamo Hipotecario",
        digits=(16, 2),
        help="Valor Prestamo Hipotecario IESS",
    )
    p_quirografario = fields.Float(
        string="Prestamo Quirografario",
        digits=(16, 2),
        help="Valor Prestamo Quirografario IESS",
    )
    anticipo_sueldo = fields.Float(
        digits=(16, 2),
        help="Valor Prestamo Anticipo de sueldo en la empresa",
    )
    otros_descuentos = fields.Float(
        digits=(16, 2),
    )
    age_days = fields.Integer(
        compute="_compute_age_days",
        string="Días de Contrato",
    )
    code_contract_id = fields.Many2one(
        "hr.contract.code",
        string="Código Sectorial",
    )

    @api.onchange("contract_date_start", "base_trial_days")
    def _onchange_trial_days(self):
        for version in self:
            if version.contract_date_start and version.base_trial_days:
                version.trial_date_end = version.contract_date_start + relativedelta(
                    days=version.base_trial_days
                )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if "trial_date_end" not in vals:
                vals.update(self._trial_date_end_vals(vals, self.browse()))
        return super().create(vals_list)

    def write(self, vals):
        if len(self) == 1 and "trial_date_end" not in vals:
            if "contract_date_start" in vals or "base_trial_days" in vals:
                vals.update(self._trial_date_end_vals(vals, self))
        return super().write(vals)

    @api.model
    def _trial_date_end_vals(self, vals, record):
        start = vals.get(
            "contract_date_start", record.contract_date_start if record else None
        )
        days = vals.get("base_trial_days", record.base_trial_days if record else None)
        start = fields.Date.to_date(start)
        if start and days:
            return {"trial_date_end": start + relativedelta(days=days)}
        return {}

    def action_end_trial(self):
        self.write({"trial_date_end": fields.Date.context_today(self)})
        return True

    def action_end_contract(self):
        for version in self:
            if not version.contract_date_start:
                raise UserError(
                    self.env._("No se puede terminar un contrato sin fecha de inicio.")
                )
            version.write(
                {
                    "contract_date_end": version.contract_date_end
                    or fields.Date.context_today(version),
                    "end_job_id": version.job_id.id,
                    "job_id": False,
                    "active": False,
                }
            )
        return True

    @api.model
    def _cron_update_state(self):
        versions = self.with_context(active_test=False).search(
            [("active", "in", [True, False])]
        )
        versions.modified(
            ["contract_date_start", "trial_date_end", "contract_date_end"]
        )
        versions.flush_recordset(["state"])
