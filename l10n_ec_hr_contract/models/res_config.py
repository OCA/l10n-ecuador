from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    l10n_ec_hr_base_trial_days = fields.Integer(
        string="Número de días para período de prueba",
        config_parameter="l10n_ec_hr_contract.base_trial_days",
        default=90,
    )
    l10n_ec_hr_wage_base_legal = fields.Float(
        string="Salario Básico Unificado Actual",
        config_parameter="l10n_ec_hr_contract.wage_base_legal",
        default=375,
    )
