from odoo import api, fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    l10n_ec_type_environment = fields.Selection(
        [
            ("test", "Test"),
            ("production", "Production"),
        ],
        string="Environment type for electronic documents",
        default="test",
    )
    l10n_ec_key_type_id = fields.Many2one(
        comodel_name="sri.key.type",
        string="Certificate File",
        ondelete="restrict",
    )
    # nombre se usara para leer el archivo xsd y validar el xml
    l10n_ec_invoice_version = fields.Selection(
        [
            ("1.0.0", "1.0.0"),
            ("1.1.0", "1.1.0"),
            ("2.0.0", "2.0.0(Third Party Items)"),
            ("2.1.0", "2.1.0(Third Party Items)"),
        ],
        string="Invoice Version xml",
        default="1.1.0",
    )

    @api.model
    def l10n_ec_get_resolution_data(self, date=None):
        # TODO: implementar logica para devolver numero de resolucion
        return ""
