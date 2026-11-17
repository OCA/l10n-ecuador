from odoo import api, fields, models
from odoo.exceptions import ValidationError

TRIBUTE_TYPES = [
    ("advalorem", "Ad Valorem"),
    ("fodinfa", "FODINFA"),
    ("ice", "ICE"),
    ("vat", "IVA"),
]


class L10nEcImportTribute(models.Model):
    _name = "l10n_ec.import.tribute"
    _description = "Ecuador Import Tribute"
    _order = "import_id, line_id, sequence, id"

    import_id = fields.Many2one("l10n_ec.import", required=True, ondelete="cascade", index=True)
    line_id = fields.Many2one("l10n_ec.import.line", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="import_id.company_id", store=True, index=True)
    currency_id = fields.Many2one(related="import_id.currency_id")
    state = fields.Selection(related="import_id.state")
    product_id = fields.Many2one(related="line_id.product_id", store=True)
    tribute_type = fields.Selection(TRIBUTE_TYPES, required=True, readonly=True)
    sequence = fields.Integer(compute="_compute_sequence", store=True)
    base_amount = fields.Monetary(string="Base", readonly=True)
    rate = fields.Float(string="Rate (%)", digits=(16, 4), readonly=True)
    computed_amount = fields.Monetary(string="Computed", readonly=True)
    relief_type = fields.Selection(
        [("none", "None"), ("percent", "Relief %"), ("effective_rate", "Effective rate")],
        string="Relief", default="none", required=True,
        help="Relief %: reduces the computed tribute by this percentage.\n"
        "Effective rate: the tribute is base x this rate (e.g. preferential tariff).",
    )
    relief_value = fields.Float(digits=(16, 4))
    relief_reason = fields.Char(
        string="Legal Reason",
        help="Legal basis of the relief (agreement, resolution, exemption article...). Required to publish.",
    )
    amount = fields.Monetary(string="Payable", compute="_compute_amount", store=True)
    relief_amount = fields.Monetary(compute="_compute_amount", store=True)

    @api.depends("tribute_type")
    def _compute_sequence(self):
        order = {key: i for i, (key, _label) in enumerate(TRIBUTE_TYPES)}
        for tribute in self:
            tribute.sequence = order.get(tribute.tribute_type, 99)

    @api.depends("computed_amount", "base_amount", "relief_type", "relief_value")
    def _compute_amount(self):
        for tribute in self:
            cur = tribute.currency_id or tribute.import_id.company_id.currency_id
            amount = tribute.computed_amount
            if tribute.relief_type == "percent":
                amount = tribute.computed_amount * (1 - tribute.relief_value / 100.0)
            elif tribute.relief_type == "effective_rate":
                amount = tribute.base_amount * tribute.relief_value / 100.0
            amount = cur.round(amount) if cur else amount
            tribute.amount = amount
            tribute.relief_amount = tribute.computed_amount - amount

    @api.depends("tribute_type", "product_id")
    def _compute_display_name(self):
        labels = dict(TRIBUTE_TYPES)
        for tribute in self:
            tribute.display_name = f"{labels.get(tribute.tribute_type, '')} - {tribute.product_id.display_name or ''}"

    @api.constrains("relief_type", "relief_value")
    def _check_relief(self):
        for tribute in self:
            if tribute.relief_value < 0:
                raise ValidationError(self.env._("The relief value cannot be negative."))
            if tribute.relief_type == "percent" and tribute.relief_value > 100:
                raise ValidationError(self.env._("A relief percentage cannot exceed 100%."))
