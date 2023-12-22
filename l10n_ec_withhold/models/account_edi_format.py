from odoo import models


class AccountEdiFormat(models.Model):
    _inherit = "account.edi.format"

    def _is_compatible_with_journal(self, journal):
        if (
            journal.country_code == "EC"
            and journal.l10n_ec_withholding_type == "purchase"
            and self.code == "l10n_ec_format_sri"
        ):
            return True
        return super()._is_compatible_with_journal(journal)

    def _get_move_applicability(self, move):
        self.ensure_one()
        if self.code == "l10n_ec_format_sri" and move.is_purchase_withhold():
            return {
                "post": self._l10n_ec_post_move_edi,
                "cancel": self._l10n_ec_cancel_move_edi,
            }
        return super()._get_move_applicability(move)
