from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class DeliveryNoteLine(models.Model):
    _name = "l10n_ec.delivery.note.line"
    _description = "Delivery Note lines"
    _rec_name = "product_id"

    delivery_note_id = fields.Many2one(
        "l10n_ec.delivery.note",
        "Delivery Note",
        ondelete="cascade",
        index=True,
        auto_join=True,
    )
    product_id = fields.Many2one(
        "product.product", "Product", index=True, auto_join=True
    )
    product_uom_category_id = fields.Many2one(related="product_id.uom_id.category_id")
    product_uom_id = fields.Many2one(
        "uom.uom",
        string="UoM",
        ondelete="restrict",
        domain="[('category_id', '=', product_uom_category_id)]",
    )
    product_qty = fields.Float("Quantity", digits="Product Unit of Measure")
    production_lot_id = fields.Many2one(
        "stock.production.lot",
        "Production Lot",
        index=True,
        domain="[('product_id', '=', product_id)]",
    )
    move_id = fields.Many2one(
        "stock.move", "Stock Move", required=False, index=True, auto_join=True
    )
    move_line_id = fields.Many2one(
        "stock.move.line", "Stock Move line", required=False, index=True, auto_join=True
    )
    company_id = fields.Many2one(
        "res.company", "Company", related="delivery_note_id.company_id", store=True
    )
    description = fields.Char()

    @api.onchange(
        "product_id",
    )
    def onchange_product_id(self):
        if self.product_id:
            self.product_uom_id = self.product_id.uom_id.id
            self.description = self.product_id.name

    @api.constrains("product_id", "product_uom_id")
    def _check_product_uom(self):
        for line in self:
            if (
                line.product_id
                and line.product_uom_id
                and line.product_id.uom_id.category_id
                != line.product_uom_id.category_id
            ):
                raise ValidationError(
                    _(
                        "You cannot perform the move "
                        "because the unit of measure: %(unit_name)s has a different category "
                        "as the product unit of measure: %(categ_name)s."
                    )
                    % {
                        "unit_name": line.product_uom_id.display_name,
                        "categ_name": line.product_id.uom_id.category_id.display_name,
                    }
                )

    @api.model
    def _prepare_delivery_note_line(self, delivery_note, stock_move_line):
        vals = {
            "delivery_note_id": delivery_note.id,
            "product_id": stock_move_line.product_id.id,
            "description": stock_move_line.move_id.sale_line_id.name
            or stock_move_line.product_id.name,
            "product_qty": stock_move_line.qty_done,
            "product_uom_id": stock_move_line.product_uom_id.id,
            "move_id": stock_move_line.move_id.id,
            "move_line_id": stock_move_line.id,
            "production_lot_id": stock_move_line.lot_id.id,
        }
        return vals

    def l10n_ec_get_delivery_note_edi_data(self):
        self.ensure_one()
        EdiDocument = self.env["account.edi.document"]
        res = {
            "codigoInterno": EdiDocument._l10n_ec_clean_str(
                self.product_id.default_code or "NA"
            )[:25],
            "codigoAdicional": False,
            "descripcion": EdiDocument._l10n_ec_clean_str(
                (self.description or "NA")[:300]
            ),
            "cantidad": EdiDocument._l10n_ec_number_format(
                self.product_qty, decimals=6
            ),
            "detallesAdicionales": self._l10n_ec_get_delivery_note_edi_additional_data(),
        }
        return res

    def _l10n_ec_get_delivery_note_edi_additional_data(self):
        res = []
        return res
