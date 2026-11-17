from collections import defaultdict

from odoo import api, fields, models


class L10nEcImportLine(models.Model):
    _name = "l10n_ec.import.line"
    _description = "Ecuador Import Product Line"
    _order = "import_id, id"

    import_id = fields.Many2one("l10n_ec.import", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="import_id.company_id", store=True, index=True)
    currency_id = fields.Many2one(related="import_id.currency_id")
    state = fields.Selection(related="import_id.state")
    product_id = fields.Many2one("product.product", required=True, readonly=True)
    uom_id = fields.Many2one(related="product_id.uom_id")
    tariff_id = fields.Many2one("l10n_ec.import.tariff", string="Tariff Subheading")
    move_ids = fields.Many2many("stock.move", string="Receipt Moves", readonly=True)
    quantity = fields.Float(digits="Product Unit", readonly=True)
    weight = fields.Float(string="Weight (kg)", digits="Stock Weight")
    volume = fields.Float(string="Volume (m³)", digits="Volume")

    fob_amount = fields.Monetary(string="FOB", readonly=True)
    freight_amount = fields.Monetary(string="Freight", readonly=True)
    insurance_amount = fields.Monetary(string="Insurance", readonly=True)
    cif_amount = fields.Monetary(string="CIF", readonly=True)
    ice_amount = fields.Monetary(
        string="ICE (declared)",
        help="ICE amount typed from the customs declaration for this product. It enters the IVA base.",
    )

    tribute_ids = fields.One2many("l10n_ec.import.tribute", "line_id", string="Tributes")
    advalorem_amount = fields.Monetary(string="Ad Valorem", compute="_compute_tributes", store=True)
    fodinfa_amount = fields.Monetary(string="FODINFA", compute="_compute_tributes", store=True)
    ice_tribute_amount = fields.Monetary(string="ICE", compute="_compute_tributes", store=True)
    vat_amount = fields.Monetary(string="IVA", compute="_compute_tributes", store=True)
    tributes_amount = fields.Monetary(string="Total Tributes", compute="_compute_tributes", store=True)
    landed_amount = fields.Monetary(
        string="Stock Cost", compute="_compute_tributes", store=True,
        help="FOB + tributes that enter stock (Ad Valorem, FODINFA, ICE) + freight/insurance when enabled.",
    )
    unit_landed_cost = fields.Monetary(string="Unit Cost", compute="_compute_tributes", store=True)

    @api.depends(
        "tribute_ids.amount", "tribute_ids.tribute_type", "fob_amount", "freight_amount", "insurance_amount",
        "quantity", "import_id.add_freight_to_stock", "import_id.add_insurance_to_stock",
    )
    def _compute_tributes(self):
        for line in self:
            totals = defaultdict(float)
            for tribute in line.tribute_ids:
                totals[tribute.tribute_type] += tribute.amount
            line.advalorem_amount = totals["advalorem"]
            line.fodinfa_amount = totals["fodinfa"]
            line.ice_tribute_amount = totals["ice"]
            line.vat_amount = totals["vat"]
            line.tributes_amount = sum(totals.values())
            landed = line.fob_amount + totals["advalorem"] + totals["fodinfa"] + totals["ice"]
            if line.import_id.add_freight_to_stock:
                landed += line.freight_amount
            if line.import_id.add_insurance_to_stock:
                landed += line.insurance_amount
            line.landed_amount = landed
            line.unit_landed_cost = landed / line.quantity if line.quantity else 0.0
