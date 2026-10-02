from odoo import models


class AccountDebitNote(models.TransientModel):
    _inherit = "account.debit.note"

    def _prepare_default_values(self, move):
        """Recover invoice data for complete debit note to Ecuador"""
        res = super()._prepare_default_values(move)

        res.update(
            l10n_ec_legacy_document_number=move.l10n_latam_document_number,
            l10n_ec_legacy_document_date=move.invoice_date,
            l10n_ec_legacy_document_authorization=move.l10n_ec_xml_access_key,
            l10n_ec_reason=self.reason,
        )

        return res
