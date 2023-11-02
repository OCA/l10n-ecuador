from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import DEFAULT_SERVER_DATE_FORMAT as DF


class WizardAbstractDeliveryNote(models.AbstractModel):
    _name = "wizard.abstract.delivery.note"
    _description = "Abstract Wizard to encapsulate logic to create new delivery notes"
    document_type = "delivery_note"

    l10n_ec_create_delivery_note = fields.Boolean(string="Create Delivery note?")
    partner_id = fields.Many2one("res.partner", string="Partner", readonly=True)
    l10n_ec_journal_id = fields.Many2one(
        comodel_name="account.journal",
        string="Journal",
        readonly=True,
        check_company=True,
        domain=[("l10n_latam_internal_type", "=", "delivery_note")],
    )
    document_number = fields.Char()
    delivery_date = fields.Date(required=False)
    transfer_date = fields.Date(required=False)
    picking_id = fields.Many2one("stock.picking", string="Picking")
    invoice_id = fields.Many2one("account.move", string="Invoice")
    rise = fields.Char("R.I.S.E")
    dau = fields.Char("D.A.U.")
    note = fields.Char()

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

    @api.model
    def default_get(self, fields_list):
        picking_model = self.env["stock.picking"]
        res = super(WizardAbstractDeliveryNote, self).default_get(fields_list)
        company = self.env.company
        picking_id = (
            res.get("picking_id", False)
            or self.env.context.get("active_id", False)
            or None
        )
        if picking_id:
            picking = picking_model.browse(picking_id)
            partner_id = None
            if picking.partner_id:
                partner_id = picking.partner_id.commercial_partner_id.id
            l10n_ec_create_delivery_note = picking.l10n_ec_create_delivery_note
            if picking.picking_type_id.code == "incoming":
                l10n_ec_create_delivery_note = False
            transfer_date = fields.Date.context_today(self)
            delivery_date = (
                transfer_date + relativedelta(days=company.l10n_ec_delivery_note_days)
            ).strftime(DF)
            res.update(
                {
                    "document_number": picking._get_next_sequence_delivery_note(),
                    "l10n_ec_create_delivery_note": l10n_ec_create_delivery_note,
                    "partner_id": partner_id,
                    "l10n_ec_journal_id": picking.l10n_ec_delivery_note_journal_id.id,
                    "delivery_date": delivery_date,
                    "transfer_date": transfer_date,
                    "picking_id": picking.id,
                }
            )
        return res

    def create_delivery_note(self):
        self.picking_id.with_context(
            delivery_note_number=self.document_number,
            delivery_date=self.delivery_date,
            transfer_date=self.transfer_date,
            invoice_id=self.invoice_id.id,
            rise=self.rise,
            dau=self.dau,
            note=self.note,
        )._l10n_ec_create_delivery_note()
        return {"type": "ir.actions.act_window_close"}


class WizardInputDocumentNumber(models.TransientModel):
    _inherit = "wizard.abstract.delivery.note"
    _name = "wizard.input.document.number"
    _description = "Wizard to enter document number to delivery note"

    def action_create_delivery_note(self):
        res = self.create_delivery_note()
        self.picking_id._action_done()
        return res


class StockBackorderConfirmation(models.TransientModel):
    _inherit = ["wizard.abstract.delivery.note", "stock.backorder.confirmation"]
    _name = "stock.backorder.confirmation"

    def process(self):
        res = super(StockBackorderConfirmation, self).process()
        if self.picking_id.l10n_ec_create_delivery_note:
            self.create_delivery_note()
        return res

    def process_cancel_backorder(self):
        res = super(StockBackorderConfirmation, self).process_cancel_backorder()
        if self.picking_id.l10n_ec_create_delivery_note:
            self.create_delivery_note()
        return res


class StockImmediateTransfer(models.TransientModel):
    _inherit = ["wizard.abstract.delivery.note", "stock.immediate.transfer"]
    _name = "stock.immediate.transfer"

    def process(self):
        res = super(StockImmediateTransfer, self).process()
        if self.picking_id.l10n_ec_create_delivery_note:
            if self.picking_id.sale_id and (
                self.picking_id.location_id
                and self.picking_id.location_dest_id.usage == "internal"
            ):
                raise UserError(
                    _(
                        "The delivery note: %(picking_name)s cannot be processed in internal "
                        "transfers created from the sales order: %(sale_name)s"
                    )
                    % (
                        {
                            "picking_name": self.picking_id.name,
                            "sale_name": self.picking_id.sale_id.name,
                        }
                    )
                )
            self.create_delivery_note()
        return res
