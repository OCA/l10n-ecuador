from collections import defaultdict

from odoo import api, models


class AccountMoveSend(models.AbstractModel):
    _inherit = "account.move.send"

    @api.model
    def _prepare_invoice_pdf_report(self, invoices_data):
        """Prepare the pdf report for the invoice passed as parameter.
        :param invoice_data:    The collected data for the invoice so far.
        """

        grouped_invoices_by_report = defaultdict(dict)
        for invoice, invoice_data in invoices_data.items():
            grouped_invoices_by_report[invoice_data["pdf_report"]][invoice] = (
                invoice_data
            )

            if invoice.is_purchase_withhold():
                if invoice.invoice_pdf_report_id:
                    return
                ActionReport = self.env["ir.actions.report"]
                report_idxml = "l10n_ec_withhold.action_report_withholding_ec"
                content, _report_format = ActionReport._render(
                    report_idxml, invoice.ids
                )
                invoice_data["pdf_attachment_values"] = {
                    "name": invoice._get_invoice_report_filename(),
                    "raw": content,
                    "mimetype": "application/pdf",
                    "res_model": invoice._name,
                    "res_id": invoice.id,
                    "res_field": "invoice_pdf_report_file",  # Binary field
                }
                return

        return super()._prepare_invoice_pdf_report(invoices_data)

    @api.model
    def _check_move_constrains(self, moves):
        if any(m.is_purchase_withhold() for m in moves):
            return

        super()._check_move_constrains(moves)
