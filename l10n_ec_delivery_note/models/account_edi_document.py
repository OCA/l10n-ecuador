import logging
from os import path

from odoo import api, fields, models
from odoo.exceptions import LockError, UserError

from odoo.addons.l10n_ec.models.res_partner import (
    PartnerIdTypeEc,
    verify_final_consumer,
)

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

    # Heredar el metodo computado, para agregar dependencia
    @api.depends("move_id", "l10n_ec_delivery_note_id")
    def _compute_l10n_ec_document_data(self):
        return super()._compute_l10n_ec_document_data()

    def _prepare_jobs(self):
        """Odoo 19 returns a list of ``{'documents', 'method_to_call'}`` dicts.

        Core derives the batching key from
        ``account.edi.format._get_move_applicability()``, which is move based
        and therefore never applies to a delivery note (``move_id`` is empty).
        Each delivery note is sent as its own job, calling the same hooks the
        invoice flow uses: ``_l10n_ec_post_move_edi`` / ``_l10n_ec_cancel_move_edi``.
        """
        delivery_note_documents = self.filtered("l10n_ec_delivery_note_id")
        jobs = super(AccountEdiDocument, self - delivery_note_documents)._prepare_jobs()
        documents = delivery_note_documents.filtered(
            lambda d: (
                d.state in ("to_send", "to_cancel") and d.blocking_level != "error"
            )
        )
        for edi_doc in documents:
            if edi_doc.state == "to_cancel":
                method_to_call = edi_doc.edi_format_id._l10n_ec_cancel_move_edi
            else:
                method_to_call = edi_doc.edi_format_id._l10n_ec_post_move_edi
            jobs.append({"documents": edi_doc, "method_to_call": method_to_call})
        return jobs

    @api.model
    def _process_job(self, job):
        documents = job["documents"].filtered("l10n_ec_delivery_note_id")
        if not documents:
            return super()._process_job(job)
        return self._l10n_ec_process_delivery_note_job(documents, job["method_to_call"])

    def _l10n_ec_process_delivery_note_job(self, documents, method_to_call):
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
        state = documents[0].state
        if state == "to_send":
            with delivery_note._send_only_when_ready():
                edi_result = method_to_call(delivery_note)
                _postprocess_post_edi_results(documents, edi_result)

    def _process_documents_no_web_services(self):
        """Post and cancel the delivery note documents without web services."""
        delivery_notes = self.filtered("l10n_ec_delivery_note_id")
        jobs = delivery_notes.filtered(
            lambda d: not d.edi_format_id._needs_web_services()
        )._prepare_jobs()
        for job in jobs:
            delivery_notes._process_job(job)
        return super(
            AccountEdiDocument, self - delivery_notes
        )._process_documents_no_web_services()

    def _process_documents_web_services(self, job_count=None, with_commit=True):
        """Post and cancel the delivery note documents needing a web service."""
        delivery_notes = self.filtered("l10n_ec_delivery_note_id")
        moves = self - delivery_notes
        nb_remaining_jobs = super(
            AccountEdiDocument, moves
        )._process_documents_web_services(job_count=job_count, with_commit=with_commit)
        all_jobs = delivery_notes.filtered(
            lambda d: d.edi_format_id._needs_web_services()
        )._prepare_jobs()
        jobs_to_process = all_jobs[0:job_count] if job_count else all_jobs
        for job in jobs_to_process:
            documents = job["documents"]
            delivery_note_to_lock = documents.l10n_ec_delivery_note_id
            attachments_potential_unlink = documents.attachment_id.filtered(
                lambda a: not a.res_model and not a.res_id
            )
            try:
                documents.lock_for_update()
                delivery_note_to_lock.lock_for_update()
                attachments_potential_unlink.lock_for_update()
            except LockError:
                _logger.debug(
                    "Another transaction already locked documents rows. "
                    "Cannot process documents."
                )
                if not with_commit:
                    raise UserError(
                        self.env._(
                            "This document is being sent by another process already."
                        )
                    ) from None
                continue
            delivery_notes._process_job(job)
            if with_commit and len(jobs_to_process) > 1:
                self.env.cr.commit()  # pylint: disable=E8102
        return nb_remaining_jobs + (len(all_jobs) - len(jobs_to_process))

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
    def _l10n_ec_get_transportista_id_type(self, carrier):
        """SRI identification code of the delivery carrier.

        ``tipoIdentificacionTransportista`` is mandatory in the SRI schema and
        is restricted to ``[0][4-8]``, so it can never be left out: QWeb drops
        the whole tag when the value is None or False (``t-esc`` compiles to
        ``if content is not None and content is not False``, see
        ``ir_qweb._compile_directive_out``), which shifted
        ``rucTransportista`` into the position where only
        ``tipoIdentificacionTransportista`` is accepted and failed the XSD
        check. The code comes from the carrier identification type the way
        ``account.move.l10n_ec_get_identification_type()`` builds the SRI
        tabla 6 code, instead of guessing from the length of the vat, which
        returned None for any vat that is neither 10 nor 13 digits. An
        unclassifiable carrier falls back to ``08`` (exterior) so the tag is
        always emitted and the XSD validates; the SRI itself still rejects a
        bad vat with DEVUELTA.
        """
        if verify_final_consumer(carrier.vat):
            return PartnerIdTypeEc.FINAL_CONSUMER.value
        code = PartnerIdTypeEc.get_ats_code_for_partner(carrier, "out_")
        return code.value if code else PartnerIdTypeEc.FOREIGN.value

    def _l10n_ec_get_info_delivery_note(self):
        delivery_note = self.l10n_ec_delivery_note_id
        commercial_partner = delivery_note.partner_id.commercial_partner_id
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
            "tipoIdentificacionTransportista": self._l10n_ec_get_transportista_id_type(
                delivery_note.delivery_carrier_id
            ),
            "rucTransportista": delivery_note.delivery_carrier_id.vat,
            "rise": delivery_note.rise if delivery_note.rise else False,
            "obligadoContabilidad": self._l10n_ec_get_required_accounting(
                company.partner_id.property_account_position_id
            ),
            "contribuyenteEspecial": company.l10n_ec_get_resolution_data(
                delivery_note.transfer_date
            ),
            "fechaIniTransporte": delivery_note.transfer_date.strftime(EDI_DATE_FORMAT),
            "fechaFinTransporte": delivery_note.delivery_date.strftime(EDI_DATE_FORMAT),
            "placa": delivery_note.l10n_ec_car_plate or "N/A",
            "identificacionDestinatario": commercial_partner.vat,
            "razonSocialDestinatario": self._l10n_ec_clean_str(commercial_partner.name)[
                :300
            ],
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
            domain + [("partner_id.vat", "not in", ["9999999999999", "9999999999"])]
        )
        for note in delivery_notes:
            note.l10n_ec_action_sent_mail_electronic()

        # Update documents with final consumer
        delivery_notes_with_final_consumer = self.env["l10n_ec.delivery.note"].search(
            domain + [("partner_id.vat", "in", ["9999999999999", "9999999999"])]
        )
        delivery_notes_with_final_consumer.write({"is_delivery_note_sent": True})

        return value
