from odoo import fields, models


class L10nEcImportContainerType(models.Model):
    _name = "l10n_ec.import.container.type"
    _description = "Container Type"
    _order = "sequence, name"

    sequence = fields.Integer(default=10)
    name = fields.Char(required=True, translate=True, help="e.g. 40' High Cube")
    code = fields.Char(help="ISO 6346 size/type code, e.g. 45G1.")
    teu = fields.Float(string="TEU", digits=(16, 1), help="Twenty-foot equivalent units (20' = 1, 40' = 2).")
    max_weight = fields.Float(string="Max. Payload (kg)", digits="Stock Weight")
    volume = fields.Float(string="Capacity (m³)", digits="Volume")
    active = fields.Boolean(default=True)
