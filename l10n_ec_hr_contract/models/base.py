# Copyright 2016 Cristian Salamea <cristian.salamea@gmail.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import api, fields, models


class HrContractBranch(models.Model):
    _name = "hr.contract.branch"
    _description = "Rama Laboral"

    code = fields.Char("Código", required=True)
    name = fields.Char("Rama", required=True)


class HrContractCommision(models.Model):
    _name = "hr.contract.commision"
    _description = "Comisión Laboral"

    code = fields.Char("Código", required=True)
    name = fields.Char("Comisión", required=True)


class HrContractCode(models.Model):
    _name = "hr.contract.code"
    _description = "Código Laboral"
    _rec_names_search = ["code", "name"]

    @api.depends("code", "name")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"{rec.code} {rec.name}"

    code = fields.Char("Código IESS", required=True, index=True)
    name = fields.Char("Cargo", required=True)
    code_structure = fields.Selection(
        [
            ("B1", "B1"),
            ("B2", "B2"),
            ("B3", "B3"),
            ("C1", "C1"),
            ("C2", "C2"),
            ("C3", "C3"),
            ("D1", "D1"),
            ("D2", "D2"),
            ("E1", "E1"),
            ("E2", "E2"),
        ],
        string="Estructura Ocupacional",
        required=True,
        default="E1",
    )
    rama_id = fields.Many2one("hr.contract.branch", string="Rama", required=True)
    commision_id = fields.Many2one(
        "hr.contract.commision",
        string="Comisión",
        required=True,
    )
