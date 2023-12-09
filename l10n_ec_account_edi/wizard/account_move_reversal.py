from odoo import models


class AccountMoveReversal(models.TransientModel):
    _inherit = "account.move.reversal"

    def _prepare_default_reversal(self, move):
        res = super()._prepare_default_reversal(move)
        res.update(
            l10n_ec_reason=self.reason,
            l10n_ec_legacy_document_number=move.l10n_latam_document_number,
            l10n_ec_legacy_document_date=move.invoice_date,
            l10n_ec_legacy_document_authorization=move.l10n_ec_xml_access_key,
        )
        return res
