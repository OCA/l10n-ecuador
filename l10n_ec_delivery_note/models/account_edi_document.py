import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class AccountEdiDocument(models.Model):
    _inherit = "account.edi.document"

    @api.model
    def l10n_ec_send_mail_to_partner(self):
        value = super().l10n_ec_send_mail_to_partner()

        domain = [
            ("state", "=", "done"),
            ("is_delivery_note_sent", "=", False),
            ("l10n_ec_authorization_date", "!=", False),
        ]
        delivery_notes = self.env["l10n_ec.delivery.note"].search(
            domain
            + [
                ("partner_id.vat", "not in", ["9999999999999", "9999999999"]),
            ]
        )
        for note in delivery_notes:
            note.l10n_ec_action_sent_mail_electronic()

        # Update documents with final consumer
        delivery_notes_with_final_consumer = self.env["l10n_ec.delivery.note"].search(
            domain
            + [
                ("partner_id.vat", "in", ["9999999999999", "9999999999"]),
            ]
        )
        delivery_notes_with_final_consumer.write({"is_delivery_note_sent": True})

        return value
