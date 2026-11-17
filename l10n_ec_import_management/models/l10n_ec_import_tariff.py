import math

from odoo import api, fields, models
from odoo.exceptions import ValidationError

RULE_TYPES = [
    ("percent", "Percentage of CIF"),
    ("per_quantity", "Specific amount per unit"),
    ("per_weight", "Specific amount per kg"),
    ("per_volume", "Specific amount per m³"),
    ("per_block", "Amount per block or fraction"),
    ("fixed", "Fixed per declaration"),
]

BLOCK_BASIS = [
    ("quantity", "Quantity"),
    ("weight", "Weight (kg)"),
    ("volume", "Volume (m³)"),
    ("cif", "CIF value"),
]


class L10nEcImportTariff(models.Model):
    _name = "l10n_ec.import.tariff"
    _description = "Ecuador Tariff Subheading"
    _order = "code"
    _rec_names_search = ["code", "name"]

    code = fields.Char(required=True, index=True, help="Subpartida arancelaria (e.g. 8471.30.00.00)")
    name = fields.Char(string="Description", required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", index=True)
    rule_ids = fields.One2many("l10n_ec.import.tariff.rule", "tariff_id", string="Ad Valorem Components", copy=True)
    note = fields.Text()

    _code_company_uniq = models.Constraint(
        "UNIQUE(code, company_id)",
        "The tariff subheading code must be unique per company.",
    )

    @api.depends("code", "name")
    def _compute_display_name(self):
        for tariff in self:
            tariff.display_name = f"{tariff.code} - {tariff.name}" if tariff.name else tariff.code

    def _compute_advalorem(self, cif, quantity, weight, volume):
        """Return the Ad Valorem amount for one product line.

        ``fixed`` components are returned separately so the caller can split
        them once per declaration among every line sharing this tariff.

        :return: (variable_amount, fixed_amount)
        """
        self.ensure_one()
        variable = fixed = 0.0
        basis_values = {"quantity": quantity, "weight": weight, "volume": volume, "cif": cif}
        for rule in self.rule_ids:
            if rule.rule_type == "percent":
                variable += cif * rule.rate / 100.0
            elif rule.rule_type == "per_quantity":
                variable += quantity * rule.amount
            elif rule.rule_type == "per_weight":
                variable += weight * rule.amount
            elif rule.rule_type == "per_volume":
                variable += volume * rule.amount
            elif rule.rule_type == "per_block":
                basis = basis_values[rule.block_basis]
                blocks = math.ceil(basis / rule.block_size - 1e-9) if basis > 0 else 0
                variable += blocks * rule.amount
            elif rule.rule_type == "fixed":
                fixed += rule.amount
        return variable, fixed


class L10nEcImportTariffRule(models.Model):
    _name = "l10n_ec.import.tariff.rule"
    _description = "Ecuador Tariff Ad Valorem Component"
    _order = "sequence, id"

    tariff_id = fields.Many2one("l10n_ec.import.tariff", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    rule_type = fields.Selection(RULE_TYPES, required=True, default="percent")
    rate = fields.Float(string="Rate (%)", digits=(16, 4))
    amount = fields.Float(digits="Product Price")
    block_size = fields.Float(default=1.0)
    block_basis = fields.Selection(BLOCK_BASIS, default="quantity")

    @api.constrains("rule_type", "rate", "amount", "block_size")
    def _check_values(self):
        for rule in self:
            if rule.rate < 0 or rule.amount < 0:
                raise ValidationError(self.env._("Tariff rates and amounts cannot be negative."))
            if rule.rule_type == "per_block" and rule.block_size <= 0:
                raise ValidationError(self.env._("The block size must be greater than zero."))
