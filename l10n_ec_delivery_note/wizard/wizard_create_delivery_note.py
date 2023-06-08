import logging

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools.safe_eval import safe_eval
from odoo.tools.translate import _

_logger = logging.getLogger(__name__)


class WizardCreateDeliveryNote(models.TransientModel):
    _name = "wizard.create.delivery.note"
    _description = "Wizard to create delivery note"

    line_ids = fields.One2many(
        comodel_name="wizard.create.delivery.note.line",
        inverse_name="wizard_id",
        string="Delivery Note lines",
        readonly=True,
    )

    @api.model
    def default_get(self, fields):
        values = super(WizardCreateDeliveryNote, self).default_get(fields)
        picking_lines = self.env["stock.picking"].browse(
            self.env.context.get("active_ids", [])
        )
        lines = []
        partner_count = {}
        for line in picking_lines.filtered(
            lambda x: x.picking_type_id.code in ("outgoing", "internal")
            and x.state == "done"
            and all(note.state == "cancel" for note in x.l10n_ec_delivery_note_ids)
        ):
            partner_count[line.partner_id] = True
            lines.append(
                (
                    0,
                    0,
                    {
                        "picking_id": line.id,
                        "name": line.name,
                        "partner_id": line.partner_id.id,
                        "location_id": line.location_id.id,
                        "location_dest_id": line.location_dest_id.id,
                        "scheduled_date": line.scheduled_date,
                        "date": line.date,
                        "origin": line.origin,
                    },
                )
            )
        if len(list(partner_count.keys())) > 1:
            raise UserError(
                _("You can only group transfers from the same company, please check")
            )
        if lines:
            values["line_ids"] = lines
        return values

    def action_create_delivery_note(self):
        self.ensure_one()
        picking_recs = self.line_ids.picking_id
        action = self.env.ref("l10n_ec_delivery_note.action_delivery_note").read()[0]
        action["views"] = [
            (self.env.ref("l10n_ec_delivery_note.view_delivery_note_form").id, "form")
        ]
        ctx = safe_eval(action["context"])
        for pick in picking_recs:
            if pick.sale_id and (
                pick.location_id and pick.location_dest_id.usage == "internal"
            ):
                raise UserError(
                    _(
                        "{} The delivery note cannot be processed in internal "
                        "transfers created from the sales order {}"
                    ).format(pick.name, pick.sale_id.name)
                )

        if self.env.company.l10n_ec_validate_invoice_exist:
            sale_order = self.line_ids.mapped("picking_id.sale_id")
            if sale_order:
                invoices = self._get_invoice_from_pickings(
                    self.line_ids.mapped("picking_id")
                )
                if not invoices:
                    raise UserError(
                        _(
                            "The delivery note cannot be processed because"
                            " the sale orders: %s do not have an invoice generated"
                        )
                        % (",".join(sale_order.mapped("name")))
                    )
                else:
                    ctx.update({"default_invoice_id": invoices[0].id})
        ctx.update(
            {
                "default_partner_id": picking_recs.partner_id.id,
                "default_stock_picking_ids": picking_recs.ids,
            }
        )
        action["context"] = ctx
        return action

    def _get_invoice_from_pickings(self, pickings):
        """
        Devolver facturas asociadas al picking
        se crea como funcion para facilitar herencia de ser necesario
        :param pickings, browse_record(stock.picking)
        : return facturas relacionadas al picking, browse_record(account.move)
        """
        return pickings.mapped("sale_id.invoice_ids").filtered(
            lambda x: x.state == "posted"
        )


class WizardCreateDeliveryNoteLine(models.TransientModel):
    _name = "wizard.create.delivery.note.line"
    _description = "Wizard to create delivery note line"

    wizard_id = fields.Many2one(
        comodel_name="wizard.create.delivery.note", string="Wizard", ondelete="cascade"
    )
    picking_id = fields.Many2one(
        comodel_name="stock.picking", string="Picking related", required=True
    )
    location_id = fields.Many2one("stock.location")
    name = fields.Char("Reference")
    location_dest_id = fields.Many2one("stock.location")
    partner_id = fields.Many2one(comodel_name="res.partner", string="Partner")
    scheduled_date = fields.Datetime()
    date = fields.Datetime("Create Date")
    origin = fields.Char()
