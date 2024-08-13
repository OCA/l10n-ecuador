from odoo import models


class MailTemplate(models.Model):
    _inherit = "mail.template"

    def _generate_template_attachments(
        self, res_ids, render_fields, render_results=None
    ):
        res = super()._generate_template_attachments(
            res_ids, render_fields, render_results
        )

        if self.model not in ["l10n_ec.delivery.note"]:
            return res

        records = self.env[self.model].browse(res_ids)
        for record in records:
            record_data = res[record.id]

            record_data.setdefault("attachment_ids", [])

            attachment = self.env["ir.attachment"].search(
                [
                    ("res_model", "=", "l10n_ec.delivery.note"),
                    ("res_id", "=", record.id),
                    ("name", "=", f"GR-{record.document_number}.xml"),
                ]
            )

            if attachment:
                record_data["attachment_ids"] += attachment.ids

        return res
