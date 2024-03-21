from odoo import models


class MailTemplate(models.Model):
    _inherit = "mail.template"

    def generate_email(self, res_ids, fields):
        res = super().generate_email(res_ids, fields)

        multi_mode = True
        if isinstance(res_ids, int):
            res_ids = [res_ids]
            multi_mode = False

        if self.model not in ["l10n_ec.delivery.note"]:
            return res

        records = self.env[self.model].browse(res_ids)
        for record in records:
            record_data = res[record.id] if multi_mode else res
            for doc in record.edi_document_ids:
                record_data.setdefault("attachments", [])
                record_data["attachments"] += self._get_edi_attachments(doc)

        return res
