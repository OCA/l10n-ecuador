from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare, float_is_zero
from odoo.tools.translate import _

STATES = {"done": [("readonly", True)], "cancel": [("readonly", True)]}


class StockPicking(models.Model):
    _inherit = "stock.picking"

    l10n_ec_delivery_note_ids = fields.Many2many(
        "l10n_ec.delivery.note", string="Delivery note", readonly=True, copy=False
    )
    l10n_ec_create_delivery_note = fields.Boolean(
        "Create Delivery note?", readonly=False, states=STATES
    )
    l10n_ec_delivery_carrier_id = fields.Many2one(
        "res.partner",
        "Delivery Note Carrier",
        readonly=False,
        states=STATES,
        domain=[("l10n_ec_is_carrier", "=", True)],
    )
    l10n_ec_car_plate = fields.Char("Car plate", size=8, readonly=False, states=STATES)
    l10n_ec_delivery_note_number = fields.Char(
        string="Delivery Note Numbers",
        index=True,
        store=True,
        compute="_compute_delivery_note_number",
    )
    l10n_ec_delivery_note_journal_id = fields.Many2one(
        comodel_name="account.journal",
        string="Emission Point",
        states=STATES,
        check_company=True,
        domain=[("l10n_latam_use_documents", "=", True), ("type", "=", "sale")],
    )
    l10n_latam_internal_type = fields.Many2one(
        "l10n_latam.document.type",
        string="Document Type",
        domain="[('code', '=', '06')]",
    )

    @api.depends("l10n_ec_delivery_note_ids.document_number")
    def _compute_delivery_note_number(self):
        for picking in self:
            picking.l10n_ec_delivery_note_number = ", ".join(
                [i.display_name for i in self.l10n_ec_delivery_note_ids]
            )

    @api.onchange("picking_type_id", "partner_id")
    def _onchange_picking_type(self):
        if self.picking_type_id and not self.l10n_ec_create_delivery_note:
            self.l10n_ec_create_delivery_note = (
                self.picking_type_id.l10n_ec_default_delivery_note
            )
        return super(StockPicking, self)._onchange_picking_type()

    @api.onchange("l10n_ec_delivery_carrier_id")
    def onchange_l10n_ec_delivery_carrier_id(self):
        if self.l10n_ec_delivery_carrier_id:
            self.l10n_ec_car_plate = (
                self.l10n_ec_delivery_carrier_id.l10n_ec_car_plate or ""
            )

    @api.model
    def l10n_ec_defined_delivery_note_type(self, picking_type_code):
        delivery_note_type = "internal"
        if picking_type_code == "outgoing":
            delivery_note_type = "sales"
        return delivery_note_type

    def button_validate(self):
        self.ensure_one()
        ctx = self.env.context.copy()
        ctx.update(
            {
                "active_id": self.id,
                "active_ids": self.ids,
                "active_model": self._name,
                "button_validate_picking_ids": self.ids,
            }
        )
        for picking in self.filtered("l10n_ec_create_delivery_note"):
            if not picking.move_lines and not picking.move_line_ids:
                raise UserError(_("Please add some lines to move"))
            # If no lots when needed, raise error
            picking_type = picking.picking_type_id
            precision_digits = self.env["decimal.precision"].precision_get(
                "Product Unit of Measure"
            )
            no_quantities_done = all(
                float_is_zero(move_line.qty_done, precision_digits=precision_digits)
                for move_line in picking.move_line_ids.filtered(
                    lambda m: m.state not in ("done", "cancel")
                )
            )

            no_reserved_quantities = all(
                float_is_zero(
                    move_line.product_qty,
                    precision_rounding=move_line.product_uom_id.rounding,
                )
                for move_line in picking.move_line_ids
            )
            if no_reserved_quantities and no_quantities_done:
                raise UserError(
                    _(
                        "You cannot validate a transfer "
                        "if has lines with quantity done equals to zero."
                        "Please, switch to Edit mode and input the done quantities."
                    )
                )
            if picking_type.use_create_lots or picking_type.use_existing_lots:
                lines_to_check = picking.move_line_ids
                if not no_quantities_done:
                    lines_to_check = lines_to_check.filtered(
                        lambda line: float_compare(
                            line.qty_done,
                            0,
                            precision_rounding=line.product_uom_id.rounding,
                        )
                    )

                for line in lines_to_check:
                    product = line.product_id
                    if product and product.tracking != "none":
                        if not line.lot_name and not line.lot_id:
                            raise UserError(
                                _(
                                    "You need to supply a Lot/Serial number for product %s."
                                )
                                % product.display_name
                            )
            if no_quantities_done:
                return super(
                    StockPicking, picking.with_context(**ctx)
                ).button_validate()
            if picking._check_backorder() and not ctx.get("skip_backorder", False):
                return picking.with_context(**ctx)._action_generate_backorder_wizard()
            if not ctx.get("skip_immediate", False) and not ctx.get(
                "skip_backorder", False
            ):
                wiz = (
                    self.env["wizard.input.document.number"]
                    .with_context(**ctx)
                    .create(
                        {
                            "picking_id": picking.id,
                            "partner_id": picking.partner_id
                            and picking.partner_id.commercial_partner_id.id
                            or None,
                            "l10n_ec_journal_id": picking.l10n_ec_delivery_note_journal_id
                            and picking.l10n_ec_delivery_note_journal_id.id
                            or None,
                            "transfer_date": fields.Date.context_today(self),
                        }
                    )
                )
                return {
                    "name": _("Create Delivery Note"),
                    "type": "ir.actions.act_window",
                    "view_type": "form",
                    "view_mode": "form",
                    "res_model": "wizard.input.document.number",
                    "target": "new",
                    "res_id": wiz.id,
                    "context": ctx,
                }
        return super(StockPicking, self.with_context(**ctx)).button_validate()

    def l10n_ec_do_print_delivery_notes(self):
        delivery_notes = self.mapped("l10n_ec_delivery_note_ids")
        return self.env.ref(
            "l10n_ec_delivery_note.action_report_delivery_note"
        ).report_action(delivery_notes)

    def _prepare_delivery_note_vals(self):
        delivery_note_number = self.env.context.get("delivery_note_number", "")
        transfer_date = self.env.context.get(
            "transfer_date", fields.Date.context_today(self)
        )
        delivery_date = self.env.context.get(
            "delivery_date", fields.Date.context_today(self)
        )
        partner_id = False
        if self.partner_id:
            if self.partner_id.parent_id:
                partner_id = self.partner_id.parent_id.id
            else:
                partner_id = self.partner_id.id
        delivery_vals = {
            "document_number": delivery_note_number,
            "transfer_date": transfer_date,
            "delivery_date": delivery_date,
            "motive": _("Create from %s") % self.name,
            "delivery_address_id": self.partner_id and self.partner_id.id or False,
            "partner_id": partner_id,
            "stock_picking_ids": [(4, self.id)],
            "delivery_carrier_id": self.l10n_ec_delivery_carrier_id.id,
            "l10n_ec_car_plate": self.l10n_ec_car_plate,
            "l10n_latam_internal_type": self.l10n_latam_internal_type.id,
            "journal_id": self.l10n_ec_delivery_note_journal_id.id,
            "invoice_id": self.env.context.get("invoice_id", False),
            "rise": self.env.context.get("rise", False),
            "dau": self.env.context.get("dau", False),
            "note": self.env.context.get("note", False),
            "delivery_note_type": self.l10n_ec_defined_delivery_note_type(
                self.picking_type_id.code
            ),
        }
        return delivery_vals

    def _l10n_ec_create_delivery_note(self):
        # Method for creation of delivery note
        delivery_note_model = self.env["l10n_ec.delivery.note"]
        delivery_note_line_obj = self.env["l10n_ec.delivery.note.line"]
        delivery_note_recs = self.env["l10n_ec.delivery.note"].browse()
        new_delivery_note = False
        for picking in self:
            if picking.l10n_ec_create_delivery_note and self.picking_type_id.code in (
                "outgoing",
                "internal",
            ):
                delivery_vals = picking._prepare_delivery_note_vals()
                new_delivery_note = delivery_note_model.create(delivery_vals)
                for move in picking.move_line_ids:
                    vals_remi_line = delivery_note_line_obj._prepare_delivery_note_line(
                        new_delivery_note, move
                    )
                    delivery_note_line_obj.create(vals_remi_line)
                new_delivery_note.action_confirm()
        if new_delivery_note:
            delivery_note_recs += new_delivery_note
            for picking in self:
                if picking.sale_id:
                    for new_delivery_note in delivery_note_recs:
                        picking.sale_id.write(
                            {"l10n_ec_delivery_note_ids": [(4, new_delivery_note.id)]}
                        )
        return delivery_note_recs.ids

    def _get_ec_formatted_sequence(self, number=0):
        return "%s-%s-%09d" % (
            self.l10n_ec_delivery_note_journal_id.l10n_ec_entity,
            self.l10n_ec_delivery_note_journal_id.l10n_ec_emission,
            number,
        )

    def _get_next_sequence_delivery_note(self):
        self.ensure_one()
        if self.l10n_ec_create_delivery_note:
            query = """
                SELECT sequence_number
                FROM l10n_ec_delivery_note
                WHERE journal_id = %(journal_id)s
                    AND document_number != '/'
                    AND sequence_prefix = (
                        SELECT sequence_prefix FROM l10n_ec_delivery_note
                        WHERE journal_id = %(journal_id)s
                            AND document_number != '/'
                        ORDER BY id DESC LIMIT 1
                    )
                ORDER BY sequence_number DESC
                LIMIT 1
            """
            params = {"journal_id": self.l10n_ec_delivery_note_journal_id.id}
            self.env.cr.execute(query, params)
            return self._get_ec_formatted_sequence(
                (self.env.cr.fetchone() or [0])[0] + 1
            )
        return ""
