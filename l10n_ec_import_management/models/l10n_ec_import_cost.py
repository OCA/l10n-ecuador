from odoo import api, fields, models

COST_TYPES = [
    ("freight", "International Freight"),
    ("insurance", "Insurance"),
    ("other", "Other Import Cost"),
]


class L10nEcImportCost(models.Model):
    """Freight, insurance and local costs of a customs declaration.

    Freight and insurance feed the CIF value (tribute base). Other costs
    (handling, broker fees, port charges...) never enter the CIF, but can be
    added to the stock value through the landed cost.
    """

    _name = "l10n_ec.import.cost"
    _description = "Import Cost"
    _order = "import_id, sequence, id"
    _check_company_auto = True

    import_id = fields.Many2one("l10n_ec.import", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="import_id.company_id", store=True, index=True)
    company_currency_id = fields.Many2one(related="import_id.currency_id", string="Company Currency")
    sequence = fields.Integer(default=10)
    cost_type = fields.Selection(COST_TYPES, string="Type", required=True, default="freight")
    partner_id = fields.Many2one("res.partner", string="Vendor", check_company=True)
    name = fields.Char(string="Description")
    vendor_bill_id = fields.Many2one(
        "account.move", string="Vendor Bill", check_company=True,
        domain="[('move_type', '=', 'in_invoice'), ('partner_id', '=?', partner_id)]",
        help="Reference only. If this bill already carries landed-cost lines, do not add the cost to stock "
        "again here to avoid counting it twice.",
    )
    currency_id = fields.Many2one(
        "res.currency", required=True, default=lambda self: self.env.company.currency_id,
    )
    amount = fields.Monetary(required=True)
    amount_company = fields.Monetary(
        string="Amount (company currency)", currency_field="company_currency_id",
        compute="_compute_amount_company", store=True,
    )
    add_to_stock = fields.Boolean(
        default=True,
        help="Other costs only: add this amount to the stock value through the landed cost. "
        "Freight and insurance follow the options of the declaration.",
    )

    @api.depends("amount", "currency_id", "import_id.arrival_date", "import_id.date", "import_id.company_id")
    def _compute_amount_company(self):
        for cost in self:
            company = cost.import_id.company_id or self.env.company
            date = cost.import_id.arrival_date or cost.import_id.date or fields.Date.context_today(cost)
            cost.amount_company = cost.currency_id._convert(cost.amount, company.currency_id, company, date)

    @api.onchange("vendor_bill_id")
    def _onchange_vendor_bill_id(self):
        bill = self.vendor_bill_id
        if bill:
            self.partner_id = bill.partner_id
            self.currency_id = bill.currency_id
            if not self.amount:
                self.amount = bill.amount_untaxed
