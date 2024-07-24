from odoo import api, models


class AccountMoveSend(models.TransientModel):
    _inherit = "account.move.send"

    @api.model
    def _prepare_invoice_pdf_report(self, invoice, invoice_data):
        """Prepare the pdf report for the invoice passed as parameter.
        :param invoice:         An account.move record.
        :param invoice_data:    The collected data for the invoice so far.
        """
        if invoice.is_purchase_withhold():
            if invoice.invoice_pdf_report_id:
                return
            ActionReport = self.env["ir.actions.report"]
            report_idxml = "l10n_ec_withhold.action_report_withholding_ec"
            content, _report_format = ActionReport._render(report_idxml, invoice.ids)
            invoice_data["pdf_attachment_values"] = {
                "raw": content,
                "name": invoice._get_invoice_report_filename(),
                "mimetype": "application/pdf",
                "res_model": invoice._name,
                "res_id": invoice.id,
                "res_field": "invoice_pdf_report_file",  # Binary field
            }
            return
        return super()._prepare_invoice_pdf_report(invoice, invoice_data)
