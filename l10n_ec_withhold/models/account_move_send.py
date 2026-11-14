from odoo import api, models


class AccountMoveSend(models.AbstractModel):
    _inherit = "account.move.send"

    @api.model
    def _prepare_invoice_pdf_report(self, invoices_data):
        """Prepare the pdf report for the invoices passed as parameter.
        :param invoices_data:    A dict keyed by account.move holding, for each
                                 invoice, the data collected so far.
        """
        withholding_report = self.env.ref(
            "l10n_ec_withhold.action_report_withholding_ec", raise_if_not_found=False
        )
        for invoice, invoice_data in invoices_data.items():
            if withholding_report and invoice.is_purchase_withhold():
                invoice_data["pdf_report"] = withholding_report
        return super()._prepare_invoice_pdf_report(invoices_data)
