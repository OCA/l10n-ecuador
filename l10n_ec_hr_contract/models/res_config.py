# -*- coding: utf-8 -*-
from odoo import fields, models


class HrConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'
    _name = 'hr.config.settings'

    default_base_trial_days = fields.Integer(
        'Número de días para período de prueba',
        default=90
    )
    default_wage_base_legal = fields.Float(
        'Salario Básico Unificado Actual',
        default=375
    )
