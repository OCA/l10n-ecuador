import io
from collections import defaultdict

import xlsxwriter

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command

from .l10n_ec_import_tribute import TRIBUTE_TYPES
from .utils import records_action

# Tributes that become part of the stock value (IVA is a tax credit, never stock).
STOCK_TRIBUTES = ("advalorem", "fodinfa", "ice")
TRIBUTE_PRODUCT_XMLIDS = {
    "advalorem": "l10n_ec_import_management.product_import_advalorem",
    "fodinfa": "l10n_ec_import_management.product_import_fodinfa",
    "ice": "l10n_ec_import_management.product_import_ice",
    "freight": "l10n_ec_import_management.product_import_freight",
    "insurance": "l10n_ec_import_management.product_import_insurance",
    "other": "l10n_ec_import_management.product_import_other",
}


class L10nEcImport(models.Model):
    _name = "l10n_ec.import"
    _description = "Ecuador Customs Declaration (Import Liquidation)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date desc, id desc"
    _check_company_auto = True

    name = fields.Char(default=lambda self: self.env._("New"), copy=False, readonly=True, tracking=True)
    dai_number = fields.Char(
        string="DAI Number", tracking=True, copy=False,
        help="Customs import declaration number (Declaración Aduanera de Importación).",
    )
    date = fields.Date(string="Declaration Date", default=fields.Date.context_today, required=True, tracking=True)
    arrival_date = fields.Date(
        help="Date used to convert the FOB value of foreign-currency purchases. "
        "Defaults to the latest receipt date when loading receipts.",
    )
    shipment_id = fields.Many2one(
        "l10n_ec.import.shipment", string="Shipment", index=True, tracking=True, check_company=True,
    )
    customs_agent_id = fields.Many2one(
        "res.partner", string="Customs Broker", tracking=True, check_company=True,
        compute="_compute_customs_agent_id", store=True, readonly=False, precompute=True,
    )
    regime_code = fields.Char(
        string="Customs Regime", default="10",
        help="Customs regime code of the DAI (10 = import for consumption).",
    )
    clearance_channel = fields.Selection(
        [("automatic", "Automatic"), ("electronic", "Electronic"), ("documentary", "Documentary"),
         ("physical", "Physical")],
        string="Inspection Channel", tracking=True, help="Aforo assigned by customs.",
    )
    release_date = fields.Date(string="Release Date", tracking=True, copy=False, help="Fecha de levante.")
    revision_ids = fields.One2many("l10n_ec.import.revision", "import_id", string="Revisions", copy=False)
    state = fields.Selection(
        [("draft", "Draft"), ("calculated", "Calculated"), ("published", "Published"), ("cancel", "Cancelled")],
        default="draft", required=True, readonly=True, copy=False, tracking=True,
    )
    company_id = fields.Many2one("res.company", required=True, index=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related="company_id.currency_id")
    customs_partner_id = fields.Many2one(
        "res.partner", string="Customs Authority",
        default=lambda self: self.env.company.l10n_ec_customs_partner_id,
    )
    picking_ids = fields.Many2many(
        "stock.picking", string="Receipts", copy=False, check_company=True,
        domain="[('state', '=', 'done'), ('picking_type_code', '=', 'incoming')]",
    )
    purchase_order_ids = fields.Many2many("purchase.order", compute="_compute_purchase_order_ids")
    vendor_bill_count = fields.Integer(compute="_compute_purchase_order_ids")

    cost_line_ids = fields.One2many("l10n_ec.import.cost", "import_id", string="Import Costs", copy=False)
    freight_amount = fields.Monetary(
        string="International Freight", tracking=True,
        compute="_compute_freight_insurance", store=True, readonly=False,
        help="Sum of the freight import costs, or typed manually when there are none.",
    )
    insurance_amount = fields.Monetary(
        string="Insurance", tracking=True,
        compute="_compute_freight_insurance", store=True, readonly=False,
        help="Sum of the insurance import costs, or typed manually when there are none.",
    )
    amount_other_costs = fields.Monetary(string="Other Costs", compute="_compute_amount_other_costs", store=True)
    add_freight_to_stock = fields.Boolean(
        string="Add Freight to Stock Value",
        help="Leave unchecked if freight already reaches stock through its own landed cost "
        "(e.g. from the forwarder's bill), to avoid counting it twice.",
    )
    add_insurance_to_stock = fields.Boolean(string="Add Insurance to Stock Value")

    fodinfa_rate = fields.Float(
        string="FODINFA (%)", digits=(16, 4), readonly=True,
        default=lambda self: self.env.company.l10n_ec_import_fodinfa_rate,
    )
    vat_rate = fields.Float(
        string="IVA (%)", digits=(16, 4), readonly=True,
        default=lambda self: self.env.company.l10n_ec_import_vat_rate,
    )

    line_ids = fields.One2many("l10n_ec.import.line", "import_id", string="Products", copy=False)
    tribute_ids = fields.One2many("l10n_ec.import.tribute", "import_id", string="Tributes", copy=False)

    landed_cost_id = fields.Many2one("stock.landed.cost", copy=False, readonly=True, check_company=True)
    customs_bill_id = fields.Many2one("account.move", string="Customs Bill", copy=False, readonly=True, check_company=True)

    amount_fob = fields.Monetary(string="FOB", compute="_compute_amounts", store=True)
    amount_freight = fields.Monetary(string="Freight", compute="_compute_amounts", store=True)
    amount_insurance = fields.Monetary(string="Insurance (allocated)", compute="_compute_amounts", store=True)
    amount_cif = fields.Monetary(string="CIF", compute="_compute_amounts", store=True)
    amount_advalorem = fields.Monetary(string="Ad Valorem", compute="_compute_amounts", store=True)
    amount_fodinfa = fields.Monetary(string="FODINFA", compute="_compute_amounts", store=True)
    amount_ice = fields.Monetary(string="ICE", compute="_compute_amounts", store=True)
    amount_vat = fields.Monetary(string="IVA", compute="_compute_amounts", store=True)
    amount_tributes = fields.Monetary(string="Payable Tributes", compute="_compute_amounts", store=True)
    amount_relief = fields.Monetary(string="Relief", compute="_compute_amounts", store=True)
    note = fields.Html()

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    @api.depends(
        "line_ids.fob_amount", "line_ids.freight_amount", "line_ids.insurance_amount", "line_ids.cif_amount",
        "tribute_ids.amount", "tribute_ids.tribute_type", "tribute_ids.relief_amount",
    )
    def _compute_amounts(self):
        for imp in self:
            imp.amount_fob = sum(imp.line_ids.mapped("fob_amount"))
            imp.amount_freight = sum(imp.line_ids.mapped("freight_amount"))
            imp.amount_insurance = sum(imp.line_ids.mapped("insurance_amount"))
            imp.amount_cif = sum(imp.line_ids.mapped("cif_amount"))
            totals = defaultdict(float)
            for tribute in imp.tribute_ids:
                totals[tribute.tribute_type] += tribute.amount
            imp.amount_advalorem = totals["advalorem"]
            imp.amount_fodinfa = totals["fodinfa"]
            imp.amount_ice = totals["ice"]
            imp.amount_vat = totals["vat"]
            imp.amount_tributes = sum(totals.values())
            imp.amount_relief = sum(imp.tribute_ids.mapped("relief_amount"))

    @api.depends("shipment_id")
    def _compute_customs_agent_id(self):
        for imp in self:
            if imp.shipment_id.customs_agent_id:
                imp.customs_agent_id = imp.shipment_id.customs_agent_id

    @api.depends("cost_line_ids.amount_company", "cost_line_ids.cost_type")
    def _compute_freight_insurance(self):
        # Without cost lines of a type, the value stays as typed by the user.
        for imp in self:
            for ctype, fname in (("freight", "freight_amount"), ("insurance", "insurance_amount")):
                costs = imp.cost_line_ids.filtered(lambda c, t=ctype: c.cost_type == t)
                if costs:
                    imp[fname] = imp.currency_id.round(sum(costs.mapped("amount_company")))

    @api.depends("cost_line_ids.amount_company", "cost_line_ids.cost_type")
    def _compute_amount_other_costs(self):
        for imp in self:
            imp.amount_other_costs = sum(
                imp.cost_line_ids.filtered(lambda c: c.cost_type == "other").mapped("amount_company")
            )

    @api.depends("picking_ids.move_ids.purchase_line_id")
    def _compute_purchase_order_ids(self):
        for imp in self:
            orders = imp.picking_ids.move_ids.purchase_line_id.order_id
            imp.purchase_order_ids = orders
            imp.vendor_bill_count = len(orders.invoice_ids)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", self.env._("New")) == self.env._("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("l10n_ec.import") or self.env._("New")
        return super().create(vals_list)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_published(self):
        if any(imp.state == "published" for imp in self):
            raise UserError(self.env._("A published import cannot be deleted. Reset it to draft first."))

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------
    def _check_editable(self):
        for imp in self:
            if imp.state not in ("draft", "calculated"):
                raise UserError(self.env._("Import %s is not in draft.", imp.name))

    def _get_import_moves(self):
        self.ensure_one()
        return self.picking_ids.move_ids.filtered(
            lambda m: m.state == "done" and m.picking_code == "incoming" and m.product_id.is_storable
        )

    def action_load_receipts(self):
        """(Re)build one product line per product from the completed receipts."""
        for imp in self:
            imp._check_editable()
            moves = imp._get_import_moves()
            if not moves:
                raise UserError(self.env._("Add at least one completed receipt with storable products."))
            missing = moves.filtered(lambda m: not m.purchase_line_id)
            if missing:
                raise UserError(self.env._(
                    "These receipt moves are not linked to a purchase order line, so their FOB is unknown:\n%s",
                    "\n".join(missing.mapped("display_name")),
                ))
            if not imp.arrival_date:
                imp.arrival_date = max(moves.mapped("date")).date()
            company = imp.company_id
            previous_ice = {line.product_id: line.ice_amount for line in imp.line_ids}
            grouped = defaultdict(lambda: {"quantity": 0.0, "fob": 0.0, "moves": self.env["stock.move"]})
            for move in moves:
                pol = move.purchase_line_id
                product = move.product_id
                qty_pol_uom = move.product_uom._compute_quantity(move.quantity, pol.product_uom_id)
                unit_net = pol.price_subtotal / pol.product_qty if pol.product_qty else 0.0
                fob = pol.currency_id._convert(unit_net * qty_pol_uom, company.currency_id, company, imp.arrival_date)
                data = grouped[product]
                data["quantity"] += move.product_uom._compute_quantity(move.quantity, product.uom_id)
                data["fob"] += fob
                data["moves"] |= move
            imp.tribute_ids.unlink()
            imp.line_ids.unlink()
            imp.write({
                "state": "draft",
                "line_ids": [Command.create({
                    "product_id": product.id,
                    "tariff_id": product.l10n_ec_tariff_id.id,
                    "quantity": data["quantity"],
                    "weight": product.weight * data["quantity"],
                    "volume": product.volume * data["quantity"],
                    "fob_amount": company.currency_id.round(data["fob"]),
                    "ice_amount": previous_ice.get(product, 0.0),
                    "move_ids": [Command.set(data["moves"].ids)],
                }) for product, data in grouped.items()],
            })
        return True

    def action_calculate(self):
        for imp in self:
            imp._check_editable()
            if not imp.line_ids:
                imp.action_load_receipts()
            imp._calculate()
        return True

    def _calculate(self):
        self.ensure_one()
        company = self.company_id
        cur = company.currency_id
        self.write({
            "fodinfa_rate": company.l10n_ec_import_fodinfa_rate,
            "vat_rate": company.l10n_ec_import_vat_rate,
        })
        lines = self.line_ids
        missing = lines.filtered(lambda line: not line.tariff_id)
        if missing:
            raise UserError(self.env._(
                "Set a tariff subheading on these products:\n%s", "\n".join(missing.product_id.mapped("display_name"))
            ))

        # 1. Freight and insurance allocated by FOB value -> CIF.
        freight_split = self._split_by_weight(self.freight_amount, lines, lines.mapped("fob_amount"))
        insurance_split = self._split_by_weight(self.insurance_amount, lines, lines.mapped("fob_amount"))
        for line in lines:
            line.write({
                "freight_amount": freight_split[line],
                "insurance_amount": insurance_split[line],
                "cif_amount": cur.round(line.fob_amount + freight_split[line] + insurance_split[line]),
            })

        # 2. Ad Valorem: variable part per line, fixed part once per tariff, split by CIF.
        advalorem = {}
        fixed_by_tariff = {}
        for line in lines:
            variable, fixed = line.tariff_id._compute_advalorem(line.cif_amount, line.quantity, line.weight, line.volume)
            advalorem[line] = variable
            fixed_by_tariff[line.tariff_id] = fixed
        for tariff, fixed in fixed_by_tariff.items():
            if fixed:
                tariff_lines = lines.filtered(lambda line, t=tariff: line.tariff_id == t)
                split = self._split_by_weight(fixed, tariff_lines, tariff_lines.mapped("cif_amount"))
                for line, value in split.items():
                    advalorem[line] += value

        # 3. Rebuild the tributes, keeping any relief already entered.
        reliefs = {
            (t.line_id.product_id.id, t.tribute_type): (t.relief_type, t.relief_value, t.relief_reason)
            for t in self.tribute_ids if t.relief_type != "none"
        }
        self.tribute_ids.unlink()
        Tribute = self.env["l10n_ec.import.tribute"]
        for line in lines:
            def make(ttype, base, rate, computed, line=line):
                relief = reliefs.get((line.product_id.id, ttype), ("none", 0.0, False))
                return Tribute.create({
                    "import_id": self.id,
                    "line_id": line.id,
                    "tribute_type": ttype,
                    "base_amount": cur.round(base),
                    "rate": rate,
                    "computed_amount": cur.round(computed),
                    "relief_type": relief[0],
                    "relief_value": relief[1],
                    "relief_reason": relief[2],
                })

            cif = line.cif_amount
            adv_rate = advalorem[line] / cif * 100.0 if cif else 0.0
            adv = make("advalorem", cif, adv_rate, advalorem[line])
            fod = make("fodinfa", cif, self.fodinfa_rate, cif * self.fodinfa_rate / 100.0)
            ice_amount = 0.0
            if line.ice_amount:
                ice_amount = make("ice", cif, line.ice_amount / cif * 100.0 if cif else 0.0, line.ice_amount).amount
            vat_base = cif + adv.amount + fod.amount + ice_amount
            make("vat", vat_base, self.vat_rate, vat_base * self.vat_rate / 100.0)
        self.state = "calculated"

    def _split_by_weight(self, total, records, weights):
        """Split ``total`` among ``records`` proportionally to ``weights``; the
        rounding difference goes to the last record so the sum is exact."""
        cur = self.company_id.currency_id
        result = dict.fromkeys(records, 0.0)
        if not records or cur.is_zero(total):
            return result
        weight_total = sum(weights)
        allocated = 0.0
        for record, weight in zip(records, weights):
            share = cur.round(total * weight / weight_total) if weight_total else cur.round(total / len(records))
            result[record] = share
            allocated += share
        result[records[-1]] = cur.round(result[records[-1]] + total - allocated)
        return result

    def action_publish(self):
        for imp in self:
            imp._check_editable()
            imp._calculate()
            unjustified = imp.tribute_ids.filtered(lambda t: t.relief_type != "none" and not t.relief_reason)
            if unjustified:
                raise UserError(self.env._(
                    "Each relief needs its legal reason before publishing:\n%s",
                    "\n".join(unjustified.mapped("display_name")),
                ))
            imp.state = "published"
        return True

    def action_reset_draft(self):
        for imp in self:
            if imp.landed_cost_id.state == "done":
                raise UserError(self.env._("The landed cost %s is already validated.", imp.landed_cost_id.name))
            if imp.customs_bill_id.state == "posted":
                raise UserError(self.env._("The customs bill %s is already posted.", imp.customs_bill_id.name))
        self.landed_cost_id.filtered(lambda lc: lc.state == "draft").unlink()
        self.customs_bill_id.filtered(lambda m: m.state == "draft").unlink()
        self.write({"state": "draft"})
        return True

    def action_cancel(self):
        self.action_reset_draft()
        self.write({"state": "cancel"})
        return True

    # ------------------------------------------------------------------
    # Landed cost and customs bill
    # ------------------------------------------------------------------
    def _get_tribute_product(self, key):
        return self.env.ref(TRIBUTE_PRODUCT_XMLIDS[key])

    def _check_published(self):
        self.ensure_one()
        if self.state != "published":
            raise UserError(self.env._("Publish the import before generating documents."))

    def action_create_landed_cost(self):
        self.ensure_one()
        self._check_published()
        if self.landed_cost_id and self.landed_cost_id.state != "cancel":
            return self.action_view_landed_cost()
        cost_lines = []

        def add(key, label, line, amount):
            if self.currency_id.is_zero(amount):
                return
            product = self._get_tribute_product(key)
            cost_lines.append(Command.create({
                "product_id": product.id,
                "name": f"{label} - {line.product_id.display_name}",
                "account_id": product.product_tmpl_id.get_product_accounts()["expense"].id,
                "price_unit": amount,
                "split_method": "by_quantity",
                "l10n_ec_product_ids": [Command.set(line.product_id.ids)],
            }))

        labels = dict(TRIBUTE_TYPES)
        for tribute in self.tribute_ids.filtered(lambda t: t.tribute_type in STOCK_TRIBUTES):
            add(tribute.tribute_type, labels[tribute.tribute_type], tribute.line_id, tribute.amount)
        for line in self.line_ids:
            if self.add_freight_to_stock:
                add("freight", self.env._("Freight"), line, line.freight_amount)
            if self.add_insurance_to_stock:
                add("insurance", self.env._("Insurance"), line, line.insurance_amount)
        # Other import costs: split among the declared products by value.
        other_product = self._get_tribute_product("other")
        for cost in self.cost_line_ids.filtered(lambda c: c.cost_type == "other" and c.add_to_stock):
            if self.currency_id.is_zero(cost.amount_company):
                continue
            cost_lines.append(Command.create({
                "product_id": other_product.id,
                "name": cost.name or cost.partner_id.display_name or self.env._("Import cost"),
                "account_id": other_product.product_tmpl_id.get_product_accounts()["expense"].id,
                "price_unit": cost.amount_company,
                "split_method": "by_current_cost_price",
                "l10n_ec_product_ids": [Command.set(self.line_ids.product_id.ids)],
            }))
        if not cost_lines:
            raise UserError(self.env._("There is no amount to add to the stock value."))
        landed_cost = self.env["stock.landed.cost"].with_company(self.company_id).create({
            "date": self.date,
            "picking_ids": [Command.set(self.line_ids.move_ids.picking_id.ids)],
            "vendor_bill_id": self.customs_bill_id.id,
            "description": self.env._("Import %(name)s - DAI %(dai)s", name=self.name, dai=self.dai_number or "-"),
            "cost_lines": cost_lines,
        })
        landed_cost.compute_landed_cost()
        self.landed_cost_id = landed_cost
        return self.action_view_landed_cost()

    def action_create_customs_bill(self):
        self.ensure_one()
        self._check_published()
        if self.customs_bill_id:
            return self.action_view_customs_bill()
        partner = self.customs_partner_id or self.company_id.l10n_ec_customs_partner_id
        if not partner:
            raise UserError(self.env._("Set the customs authority on the import or in the settings."))
        vat_account = self.company_id.l10n_ec_import_vat_account_id
        if not vat_account and not self.currency_id.is_zero(self.amount_vat):
            raise UserError(self.env._("Configure the 'IVA on Imports Account' in the settings."))
        labels = dict(TRIBUTE_TYPES)
        lines = []
        for ttype in STOCK_TRIBUTES:
            amount = sum(self.tribute_ids.filtered(lambda t, tt=ttype: t.tribute_type == tt).mapped("amount"))
            if self.currency_id.is_zero(amount):
                continue
            product = self._get_tribute_product(ttype)
            lines.append(Command.create({
                "product_id": product.id,
                "name": f"{labels[ttype]} - DAI {self.dai_number or self.name}",
                "quantity": 1,
                "price_unit": amount,
                "tax_ids": [Command.clear()],
                "is_landed_costs_line": True,
            }))
        if not self.currency_id.is_zero(self.amount_vat):
            lines.append(Command.create({
                "name": self.env._("IVA on imports - DAI %s", self.dai_number or self.name),
                "account_id": vat_account.id,
                "quantity": 1,
                "price_unit": self.amount_vat,
                "tax_ids": [Command.clear()],
            }))
        if not lines:
            raise UserError(self.env._("There are no tributes to bill."))
        vals = {
            "move_type": "in_invoice",
            "partner_id": partner.id,
            "company_id": self.company_id.id,
            "invoice_date": self.date,
            "ref": self.dai_number or self.name,
            "invoice_origin": self.name,
            "currency_id": self.currency_id.id,
            "invoice_line_ids": lines,
        }
        if self.company_id.l10n_ec_import_journal_id:
            vals["journal_id"] = self.company_id.l10n_ec_import_journal_id.id
        bill = self.env["account.move"].with_company(self.company_id).create(vals)
        self.customs_bill_id = bill
        if self.landed_cost_id and not self.landed_cost_id.vendor_bill_id:
            self.landed_cost_id.vendor_bill_id = bill
        return self.action_view_customs_bill()

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------
    def action_view_landed_cost(self):
        self.ensure_one()
        return records_action(self.landed_cost_id, self.env._("Landed Cost"))

    def action_view_customs_bill(self):
        self.ensure_one()
        return records_action(self.customs_bill_id, self.env._("Customs Bill"))

    def action_view_vendor_bills(self):
        self.ensure_one()
        return records_action(self.purchase_order_ids.invoice_ids, self.env._("Vendor Bills"))

    def action_view_shipment(self):
        self.ensure_one()
        return records_action(self.shipment_id, self.env._("Shipment"))

    def action_view_pickings(self):
        self.ensure_one()
        return records_action(self.picking_ids, self.env._("Receipts"))

    # ------------------------------------------------------------------
    # Excel export
    # ------------------------------------------------------------------
    def action_export_xlsx(self):
        self.ensure_one()
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True})
        bold = workbook.add_format({"bold": True, "bg_color": "#D9E1F2", "border": 1})
        money = workbook.add_format({"num_format": "#,##0.00"})
        qty = workbook.add_format({"num_format": "#,##0.####"})
        _ = self.env._

        sheet = workbook.add_worksheet(_("Products"))
        headers = [_("Product"), _("Tariff"), _("Quantity"), _("Weight"), _("FOB"), _("Freight"),
                   _("Insurance"), _("CIF"), _("Ad Valorem"), _("FODINFA"), _("ICE"), _("IVA"), _("Tributes")]
        sheet.write_row(0, 0, headers, bold)
        for row, line in enumerate(self.line_ids, start=1):
            sheet.write(row, 0, line.product_id.display_name)
            sheet.write(row, 1, line.tariff_id.code or "")
            sheet.write(row, 2, line.quantity, qty)
            sheet.write(row, 3, line.weight, qty)
            for col, value in enumerate([
                line.fob_amount, line.freight_amount, line.insurance_amount, line.cif_amount,
                line.advalorem_amount, line.fodinfa_amount, line.ice_tribute_amount, line.vat_amount,
                line.tributes_amount,
            ], start=4):
                sheet.write(row, col, value, money)
        sheet.set_column(0, 0, 40)
        sheet.set_column(1, 12, 14)

        sheet = workbook.add_worksheet(_("Tributes"))
        headers = [_("Product"), _("Tribute"), _("Base"), _("Rate %"), _("Computed"), _("Relief"),
                   _("Relief Value"), _("Reason"), _("Payable")]
        sheet.write_row(0, 0, headers, bold)
        relief_labels = dict(self.env["l10n_ec.import.tribute"]._fields["relief_type"]._description_selection(self.env))
        type_labels = dict(self.env["l10n_ec.import.tribute"]._fields["tribute_type"]._description_selection(self.env))
        for row, tribute in enumerate(self.tribute_ids, start=1):
            sheet.write(row, 0, tribute.product_id.display_name)
            sheet.write(row, 1, type_labels[tribute.tribute_type])
            sheet.write(row, 2, tribute.base_amount, money)
            sheet.write(row, 3, tribute.rate, qty)
            sheet.write(row, 4, tribute.computed_amount, money)
            sheet.write(row, 5, relief_labels[tribute.relief_type])
            sheet.write(row, 6, tribute.relief_value, qty)
            sheet.write(row, 7, tribute.relief_reason or "")
            sheet.write(row, 8, tribute.amount, money)
        sheet.set_column(0, 0, 40)
        sheet.set_column(1, 8, 14)
        sheet.set_column(7, 7, 40)
        workbook.close()

        attachment = self.env["ir.attachment"].create({
            "name": f"{self.name.replace('/', '_')}.xlsx",
            "raw": output.getvalue(),
            "res_model": self._name,
            "res_id": self.id,
            "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        })
        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{attachment.id}?download=true",
            "target": "self",
        }
