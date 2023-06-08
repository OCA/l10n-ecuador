import logging
from os import path

from psycopg2 import OperationalError

from odoo import _, api, fields, models
from odoo.exceptions import UserError

EDI_DATE_FORMAT = "%d/%m/%Y"
DEFAULT_BLOCKING_LEVEL = "error"

_logger = logging.getLogger(__name__)


class AccountEdiDocument(models.Model):
    _inherit = "account.edi.document"

    l10n_ec_delivery_note_id = fields.Many2one(
        comodel_name="l10n_ec.delivery.note",
        string="Delivery delivery_note",
        required=False,
        ondelete="cascade",
    )
    move_id = fields.Many2one(required=False)

    # Heredar el método computado, para agregar dependencia
    @api.depends("l10n_ec_delivery_note_id")
    def _compute_l10n_ec_document_data(self):
        return super()._compute_l10n_ec_document_data()

    def _prepare_jobs(self):
        if self.move_id:
            return super()._prepare_jobs()
        to_process = {}
        documents = self.filtered(
            lambda d: d.state in ("to_send", "to_cancel")
            and d.blocking_level != "error"
        )
        for edi_doc in documents:
            delivery_note = edi_doc.l10n_ec_delivery_note_id
            edi_format = edi_doc.edi_format_id
            custom_key = edi_format._get_batch_key(delivery_note, edi_doc.state)
            key = (edi_format, edi_doc.state, delivery_note.company_id, custom_key)
            to_process.setdefault(key, self.env["account.edi.document"])
            to_process[key] |= edi_doc

        delivery_notes = []
        for key, documents in to_process.items():
            edi_format, state, company_id, custom_key = key
            batch = self.env["account.edi.document"]
            for doc in documents:
                if edi_format._support_batching(
                    doc.l10n_ec_delivery_note_id, state=state, company=company_id
                ):
                    batch |= doc
                else:
                    delivery_notes.append(doc)
            if batch:
                delivery_notes.append(batch)
        return delivery_notes

    @api.model
    def _process_job(self, documents, doc_type=None):
        if self.move_id:
            return super()._process_job(documents, doc_type)

        def _postprocess_post_edi_results(documents, edi_result):
            attachments_to_unlink = self.env["ir.attachment"]
            for document in documents:
                delivery_note = document.l10n_ec_delivery_note_id
                delivery_note_result = edi_result.get(delivery_note, {})
                if delivery_note_result.get("attachment"):
                    old_attachment = document.attachment_id
                    document.attachment_id = delivery_note_result["attachment"]
                    if not old_attachment.res_model or not old_attachment.res_id:
                        attachments_to_unlink |= old_attachment
                if delivery_note_result.get("success") is True:
                    document.write(
                        {
                            "state": "sent",
                            "error": False,
                            "blocking_level": False,
                        }
                    )
                else:
                    document.write(
                        {
                            "error": delivery_note_result.get("error", False),
                            "blocking_level": delivery_note_result.get(
                                "blocking_level", DEFAULT_BLOCKING_LEVEL
                            )
                            if "error" in delivery_note_result
                            else False,
                        }
                    )
            attachments_to_unlink.unlink()

        delivery_note = documents.l10n_ec_delivery_note_id
        documents.edi_format_id.ensure_one()
        delivery_note.company_id.ensure_one()
        if len({doc.state for doc in documents}) != 1:
            raise ValueError(
                "All account.edi.document of a job should have the same state"
            )
        edi_format = documents.edi_format_id
        state = documents[0].state
        if state == "to_send":
            with delivery_note._send_only_when_ready():
                edi_result = edi_format._post_invoice_edi(delivery_note)
                _postprocess_post_edi_results(documents, edi_result)

    def _process_documents_no_web_services(self):
        moves = self.filtered("move_id")
        delivery_notes = self - moves
        jobs = delivery_notes.filtered(
            lambda d: not d.edi_format_id._needs_web_services()
        )._prepare_jobs()
        for documents in jobs:
            delivery_notes._process_job(documents)
        return super(AccountEdiDocument, moves)._process_documents_no_web_services()

    def _process_documents_web_services(self, job_count=None, with_commit=True):
        moves = self.filtered("move_id")
        super(AccountEdiDocument, moves)._process_documents_web_services()
        delivery_notes = self - moves
        all_jobs = delivery_notes.filtered(
            lambda d: d.edi_format_id._needs_web_services()
        )._prepare_jobs()
        jobs_to_process = all_jobs[0:job_count] if job_count else all_jobs
        for documents in jobs_to_process:
            move_to_lock = documents.l10n_ec_delivery_note_id
            attachments_potential_unlink = documents.attachment_id.filtered(
                lambda a: not a.res_model and not a.res_id
            )
            try:
                with self.env.cr.savepoint(flush=False):
                    self._cr.execute(
                        "SELECT * FROM account_edi_document WHERE id IN %s FOR UPDATE NOWAIT",
                        [tuple(documents.ids)],
                    )
                    self._cr.execute(
                        "SELECT * FROM l10n_ec_delivery_note WHERE id IN %s FOR UPDATE NOWAIT",
                        [tuple(move_to_lock.ids)],
                    )
                    # Locks the attachments that might be unlinked
                    if attachments_potential_unlink:
                        self._cr.execute(
                            "SELECT * FROM ir_attachment WHERE id IN %s FOR UPDATE NOWAIT",
                            [tuple(attachments_potential_unlink.ids)],
                        )
            except OperationalError as e:
                if e.pgcode == "55P03":
                    _logger.debug(
                        "Another transaction already locked documents rows. "
                        "Cannot process documents."
                    )
                    if not with_commit:
                        raise UserError(
                            _(
                                "This document is being sent"
                                " by another process already."
                            )
                        ) from None
                    continue
                else:
                    raise e
            delivery_notes._process_job(documents)
            if with_commit and len(jobs_to_process) > 1:
                self.env.cr.commit()  # pylint: disable=E8102
        return len(all_jobs) - len(jobs_to_process)

    def _l10n_ec_render_xml_edi(self):
        if self.move_id:
            return super()._l10n_ec_render_xml_edi()
        ViewModel = self.env["ir.ui.view"].sudo()
        xml_file = ViewModel._render_template(
            "l10n_ec_delivery_note.l10n_ec_delivery_note",
            self._l10n_ec_get_info_delivery_note(),
        )
        return xml_file

    def _l10n_ec_get_xsd_filename(self):
        if self.move_id:
            return super()._l10n_ec_get_xsd_filename()
        base_path = path.join("l10n_ec_delivery_note", "data", "xsd")
        company = self.l10n_ec_delivery_note_id.company_id or self.env.company
        filename = f"GuiaRemision_V{company.l10n_ec_delivery_note_version}"
        return path.join(base_path, f"{filename}.xsd")

    def _l10n_ec_get_edi_number(self):
        if self.l10n_ec_delivery_note_id:
            return self.l10n_ec_delivery_note_id.document_number
        return super()._l10n_ec_get_edi_number()

    @api.model
    def l10n_ec_get_type_identification(self, number):
        if len(number) == 10:
            return "05"
        elif len(number) == 13:
            return "04"

    def _l10n_ec_get_info_delivery_note(self):
        delivery_note = self.l10n_ec_delivery_note_id
        invoice = True if delivery_note.invoice_id else False
        edi_doc_invoice = delivery_note.invoice_id.edi_document_ids
        company = self.l10n_ec_delivery_note_id.company_id
        address = (
            delivery_note.delivery_address_id
            and delivery_note.delivery_address_id.street
            or "NA"
        )
        delivery_note_data = {
            "dirEstablecimiento": self._l10n_ec_clean_str(
                delivery_note.journal_id.l10n_ec_emission_address_id.street or ""
            )[:300],
            "dirPartida": self._l10n_ec_clean_str(
                delivery_note.journal_id.l10n_ec_emission_address_id.street or ""
            )[:300],
            "razonSocialTransportista": self._l10n_ec_clean_str(
                delivery_note.delivery_carrier_id.name
            )[:300],
            "tipoIdentificacionTransportista": self.l10n_ec_get_type_identification(
                delivery_note.delivery_carrier_id.vat
            ),
            "rucTransportista": delivery_note.delivery_carrier_id.vat,
            "rise": delivery_note.rise if delivery_note.rise else False,
            "obligadoContabilidad": self._l10n_ec_get_required_accounting(
                company.partner_id.property_account_position_id
            ),
            "contribuyenteEspecial": delivery_note.company_id.l10n_ec_get_resolution_data(
                delivery_note.transfer_date
            ),
            "fechaIniTransporte": delivery_note.transfer_date.strftime(EDI_DATE_FORMAT),
            "fechaFinTransporte": delivery_note.delivery_date.strftime(EDI_DATE_FORMAT),
            "placa": delivery_note.l10n_ec_car_plate or "N/A",
            "identificacionDestinatario": delivery_note.partner_id.commercial_partner_id.vat,
            "razonSocialDestinatario": self._l10n_ec_clean_str(
                delivery_note.partner_id.commercial_partner_id.name
            )[:300],
            "dirDestinatario": self._l10n_ec_clean_str(address)[:300],
            "motivoTraslado": self._l10n_ec_clean_str(delivery_note.motive or "N/A")[
                :300
            ],
            "docAduaneroUnico": delivery_note.dau if delivery_note.dau else False,
            "invoice": invoice,
            "codDocSustento": "01" if invoice else False,
            "numDocSustento": delivery_note.invoice_id.l10n_latam_document_number
            if invoice
            else False,
            "numAutDocSustento": edi_doc_invoice.l10n_ec_xml_access_key
            if invoice
            else False,
            "fechaEmisionDocSustento": delivery_note.invoice_id.invoice_date.strftime(
                EDI_DATE_FORMAT
            )
            if invoice
            else False,
            "detalles": self._l10n_ec_get_details_delivery_note(delivery_note),
            "infoAdicional": self._l10n_ec_get_info_additional(),
        }
        delivery_note_data.update(self._l10n_ec_get_info_tributaria(delivery_note))
        return delivery_note_data

    def _l10n_ec_get_details_delivery_note(self, delivery_note):
        res = []
        for line in delivery_note.delivery_line_ids:
            res.append(line.l10n_ec_get_delivery_note_edi_data())
        return res

    def l10n_ec_get_current_document(self):
        self.ensure_one()
        if self.l10n_ec_delivery_note_id:
            return self.l10n_ec_delivery_note_id
        return super().l10n_ec_get_current_document()

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
