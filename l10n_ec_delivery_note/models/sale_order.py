from odoo import api, fields, models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    l10n_ec_delivery_note_ids = fields.Many2many(
        "l10n_ec.delivery.note",
        "sale_order_delivery_note_rel",
        "order_id",
        "delivery_note_id",
        "Delivery Note",
        readonly=True,
        copy=False,
    )
    l10n_ec_delivery_note_count = fields.Integer(
        "# Delivery note", compute="_compute_delivery_note_count"
    )

    @api.depends("l10n_ec_delivery_note_ids")
    def _compute_delivery_note_count(self):
        for order in self:
            order.l10n_ec_delivery_note_count = len(order.l10n_ec_delivery_note_ids)

    def action_view_l10n_ec_delivery_note(self):
        delivery_notes = self.mapped("l10n_ec_delivery_note_ids")
        action = self.env.ref("l10n_ec_delivery_note.action_delivery_note").read()[0]
        if len(delivery_notes) > 1:
            action["domain"] = [("id", "in", delivery_notes.ids)]
        elif len(delivery_notes) == 1:
            form_view = [
                (
                    self.env.ref("l10n_ec_delivery_note.view_delivery_note_form").id,
                    "form",
                )
            ]
            if "views" in action:
                action["views"] = form_view + [
                    (state, view) for state, view in action["views"] if view != "form"
                ]
            else:
                action["views"] = form_view
            action["res_id"] = delivery_notes.id
        return action
