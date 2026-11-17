from odoo import fields, models
from odoo.exceptions import UserError


class StockLandedCostLines(models.Model):
    _inherit = "stock.landed.cost.lines"

    l10n_ec_product_ids = fields.Many2many(
        "product.product", string="Apply Only On",
        help="When set, this cost is split only among the receipt moves of these products "
        "(e.g. the Ad Valorem of one product never raises the cost of another).",
    )


class StockLandedCost(models.Model):
    _inherit = "stock.landed.cost"

    def compute_landed_cost(self):
        res = super().compute_landed_cost()
        for cost in self:
            for cost_line in cost.cost_lines.filtered("l10n_ec_product_ids"):
                adjustments = cost.valuation_adjustment_lines.filtered(lambda a, cl=cost_line: a.cost_line_id == cl)
                if not adjustments:
                    continue
                targets = adjustments.filtered(lambda a, cl=cost_line: a.product_id in cl.l10n_ec_product_ids)
                if not targets:
                    raise UserError(self.env._(
                        "The cost '%(cost)s' must apply on %(products)s, which are not in the receipts "
                        "or are not valued at FIFO/average cost.",
                        cost=cost_line.name,
                        products=", ".join(cost_line.l10n_ec_product_ids.mapped("display_name")),
                    ))
                (adjustments - targets).write({"additional_landed_cost": 0.0})
                for adjustment, value in cost._l10n_ec_split(cost_line, targets).items():
                    adjustment.additional_landed_cost = value
        return res

    def _l10n_ec_split(self, cost_line, adjustments):
        """Split ``cost_line.price_unit`` among ``adjustments`` with the line's
        split method; the rounding difference goes to the last one."""
        cur = self.currency_id
        basis = {
            "by_quantity": "quantity",
            "by_weight": "weight",
            "by_volume": "volume",
            "by_current_cost_price": "former_cost",
        }.get(cost_line.split_method)
        weights = [adj[basis] if basis else 1.0 for adj in adjustments]
        if not sum(weights):
            weights = [1.0] * len(adjustments)
        weight_total = sum(weights)
        result, allocated = {}, 0.0
        for adjustment, weight in zip(adjustments, weights):
            result[adjustment] = cur.round(cost_line.price_unit * weight / weight_total)
            allocated += result[adjustment]
        last = adjustments[-1]
        result[last] = cur.round(result[last] + cost_line.price_unit - allocated)
        return result
