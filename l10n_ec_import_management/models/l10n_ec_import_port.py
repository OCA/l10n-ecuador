from odoo import api, fields, models


class L10nEcImportPort(models.Model):
    _name = "l10n_ec.import.port"
    _description = "Port / Customs Point"
    _order = "name"
    _rec_names_search = ["code", "name"]

    name = fields.Char(required=True, translate=True)
    code = fields.Char(help="UN/LOCODE or internal code, e.g. ECGYE.")
    country_id = fields.Many2one("res.country", required=True)
    state_id = fields.Many2one("res.country.state", string="State", domain="[('country_id', '=', country_id)]")
    is_water = fields.Boolean(string="Sea")
    is_air = fields.Boolean(string="Air")
    is_land = fields.Boolean(string="Land")
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", index=True, help="Leave empty to share the port between companies.")

    @api.depends("code", "name")
    def _compute_display_name(self):
        for port in self:
            port.display_name = f"[{port.code}] {port.name}" if port.code else port.name
