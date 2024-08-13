from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.translate import _


class StockPicking(models.Model):
    _inherit = "stock.picking"

    l10n_ec_delivery_note_ids = fields.Many2many(
        "l10n_ec.delivery.note", string="Delivery note", readonly=True, copy=False
    )
    l10n_ec_create_delivery_note = fields.Boolean("Create Delivery note?")
    delivery_date = fields.Date(required=False)
    transfer_date = fields.Date(required=False)
    l10n_ec_delivery_carrier_id = fields.Many2one(
        "res.partner",
        "Delivery Note Carrier",
        domain=[("l10n_ec_is_carrier", "=", True)],
    )
    l10n_ec_car_plate = fields.Char("Car plate", size=8)
    l10n_ec_delivery_note_number = fields.Char(
        string="Delivery Note Numbers",
        index=True,
        store=True,
        compute="_compute_delivery_note_number",
    )
    l10n_ec_delivery_note_journal_id = fields.Many2one(
        comodel_name="account.journal",
        string="Emission Point",
        check_company=True,
        domain=[("l10n_latam_use_documents", "=", True), ("type", "=", "sale")],
    )

    rise = fields.Char(string="R.I.S.E", required=False)
    dau = fields.Char(string="D.A.U.", required=False)

    @api.depends("l10n_ec_delivery_note_ids.document_number")
    def _compute_delivery_note_number(self):
        for picking in self:
            picking.l10n_ec_delivery_note_number = ", ".join(
                [i.display_name for i in self.l10n_ec_delivery_note_ids]
            )

    @api.onchange("transfer_date")
    def onchange_delivery_date(self):
        if self.transfer_date:
            self.delivery_date = self.transfer_date + relativedelta(
                days=self.env.company.l10n_ec_delivery_note_days
            )

    @api.onchange("delivery_date")
    @api.constrains("transfer_date", "delivery_date")
    def _check_transfer_dates(self):
        for wizard in self:
            if (
                wizard.transfer_date
                and wizard.delivery_date
                and wizard.delivery_date < wizard.transfer_date
            ):
                raise ValidationError(
                    _("The Delivery Date can't less than transfer date, please check")
                )

    @api.onchange("picking_type_id", "partner_id")
    def _onchange_picking_type(self):
        if self.picking_type_id and not self.l10n_ec_create_delivery_note:
            self.l10n_ec_create_delivery_note = (
                self.picking_type_id.l10n_ec_default_delivery_note
            )
        return super()._onchange_picking_type()

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
            if not self.env.context.get("skip_sanity_check", False):
                picking._sanity_check()
            # Run the pre-validation wizards. Processing a pre-validation wizard
            # should work on the moves and/or the context and never call `_action_done`.
            if not self.env.context.get("button_validate_picking_ids"):
                self = self.with_context(button_validate_picking_ids=self.ids)
            res = self._pre_action_done_hook()
            if res is not True:
                return res

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

        # Create new function
        invoice = self.get_invoice()

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
            "journal_id": self.l10n_ec_delivery_note_journal_id.id,
            "invoice_id": invoice.id,
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

    def _action_done(self):
        for picking in self:
            picking._l10n_ec_create_delivery_note()

        return super()._action_done()

    def get_invoice(self):
        return self.sale_id.invoice_ids.filtered(lambda i: i.move_type == "out_invoice")
