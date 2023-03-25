import logging
import traceback
from datetime import datetime

from zeep import Client
from zeep.transports import Transport

from odoo import _, api, models, tools
from odoo.tools import float_compare, formatLang

_logger = logging.getLogger(__name__)

TEST_URL = {
    "reception": "https://celcer.sri.gob.ec/comprobantes-electronicos-ws/RecepcionComprobantesOffline?wsdl",  # noqa: B950
    "authorization": "https://celcer.sri.gob.ec/comprobantes-electronicos-ws/AutorizacionComprobantesOffline?wsdl",  # noqa: B950
}

PRODUCTION_URL = {
    "reception": "https://cel.sri.gob.ec/comprobantes-electronicos-ws/RecepcionComprobantesOffline?wsdl",  # noqa: B950
    "authorization": "https://cel.sri.gob.ec/comprobantes-electronicos-ws/AutorizacionComprobantesOffline?wsdl",  # noqa: B950
}


class AccountEdiFormat(models.Model):
    _inherit = "account.edi.format"

    def _needs_web_services(self):
        if self.code in ("l10n_ec_format_sri",):
            return True
        return super()._needs_web_services()

    def _is_compatible_with_journal(self, journal):
        if (
            journal.country_code == "EC"
            and journal.l10n_ec_emission_type == "electronic"
            and journal.l10n_latam_use_documents
            and self.code == "l10n_ec_format_sri"
        ):
            return True
        return super()._is_compatible_with_journal(journal)

    def _is_required_for_invoice(self, invoice):
        if (
            invoice.country_code != "EC"
            or invoice.journal_id.l10n_ec_emission_type != "electronic"
        ):
            return super()._is_required_for_invoice(invoice)
        if (
            self.code in ("l10n_ec_format_sri",)
            and invoice.is_sale_document()
            or (invoice.l10n_latam_internal_type == "purchase_liquidation")
        ):
            return True
        return False

    def _check_move_configuration(self, document):
        errors = super()._check_move_configuration(document)
        if document.country_code == "EC":
            l10n_ec_final_consumer_limit = float(
                self.env["ir.config_parameter"]
                .sudo()
                .get_param("l10n_ec_final_consumer_limit", 50)
            )
            company = document.company_id or self.env.company
            journal = document.journal_id
            document_type = document.l10n_latam_document_type_id.internal_type
            taxes = document.invoice_line_ids.mapped("tax_ids")
            for tax in taxes:
                if tax.tax_group_id.l10n_ec_type == "withhold_income_tax":
                    if not tax.l10n_ec_code_ats:
                        errors.append(
                            _(
                                "You must set Code Base into Tax: %s",
                                tax.display_name,
                            )
                        )
                else:
                    if not tax.l10n_ec_xml_fe_code:
                        errors.append(
                            _(
                                "You must set Tax Code for Electronic Documents into Tax: %s",
                                tax.display_name,
                            )
                        )
            # forma de pago por defecto
            if (
                not document.l10n_ec_sri_payment_id
                and not journal.l10n_ec_sri_payment_id
            ):
                errors.append(
                    _(
                        "You must set Payment Method SRI on Current document or Journal: %s",
                        journal.display_name,
                    )
                )
            # validaciones varias segun el tipo de documento
            if document_type == "invoice" and document.move_type == "out_invoice":
                if not company.l10n_ec_invoice_version:
                    errors.append(
                        _(
                            "You must set XML Version for Invoice into company %s",
                            company.display_name,
                        )
                    )
                # Validación de monto limite para Consumidor Final
                final_consumer = self.env.ref("l10n_ec.ec_final_consumer")
                if (
                    document.commercial_partner_id == final_consumer
                    and float_compare(
                        document.amount_total,
                        l10n_ec_final_consumer_limit,
                        precision_digits=2,
                    )
                    == 1
                ):
                    errors.append(
                        _(
                            "The amount total %(Total)s is bigger than "
                            "%(Limit)s for final customer"
                        )
                        % {
                            "Total": formatLang(
                                self.env,
                                document.amount_total,
                                currency_obj=company.currency_id,
                            ),
                            "Limit": formatLang(
                                self.env,
                                l10n_ec_final_consumer_limit,
                                currency_obj=company.currency_id,
                            ),
                        }
                    )
            if (
                document_type == "purchase_liquidation"
                and document.move_type == "in_invoice"
            ):
                if not company.l10n_ec_liquidation_version:
                    errors.append(
                        _(
                            "You must set XML Version for Purchase Liquidation into company %s",
                            company.display_name,
                        )
                    )
            if document_type == "credit_note" and document.move_type == "out_refund":
                # TODO YRO credit note add more validations
                if not company.l10n_ec_credit_note_version:
                    errors.append(
                        _(
                            "You must set XML Version for Credit Note into company %s",
                            company.display_name,
                        )
                    )
            # TODO: agregar logica para demas tipos de documento
            errors.extend(self._l10n_ec_check_edi_configuration(journal, company))
        return errors

    def _l10n_ec_check_edi_configuration(self, journal, company):
        errors = []
        contact_address = journal.l10n_ec_emission_address_id
        if not company.vat:
            errors.append(
                _(
                    "You must set vat identification for company: %s",
                    company.display_name,
                )
            )
        if not company.l10n_ec_key_type_id:
            errors.append(
                _(
                    "You must set Electronic Certificate File into company: %s",
                    company.display_name,
                )
            )
        if not contact_address:
            errors.append(
                _(
                    "You must set Emission address into Journal: %s",
                    journal.display_name,
                )
            )
        # direccion de establecimiento
        elif not contact_address.street:
            errors.append(
                _(
                    "You must set street into Emission Address: %(concact_name)s "
                    "for Journal: %(journal_name)s",
                    concact_name=contact_address.display_name,
                    journal_name=journal.display_name,
                )
            )
        return errors

    def _post_invoice_edi(self, documents):
        res = {}
        if self.code not in ("l10n_ec_format_sri",):
            return super()._post_invoice_edi(documents)
        # tomar la primer company, todos los documentos deben pertenecer a la misma company
        company = documents[0].company_id or self.env.company
        client_send = self._l10n_ec_get_edi_ws_client(
            company.l10n_ec_type_environment, "reception"
        )
        auth_client = self._l10n_ec_get_edi_ws_client(
            company.l10n_ec_type_environment, "authorization"
        )
        for document in documents:
            edi_docs = document.edi_document_ids.filtered(
                lambda x: x.edi_format_id.code in ("l10n_ec_format_sri",)
            )
            if edi_docs:
                document.write({"l10n_ec_is_edi_doc": True})
            errors = []
            is_auth = False
            try:
                for edi_doc in edi_docs:
                    attachment = edi_doc.attachment_id
                    xml_file = edi_doc._l10n_ec_render_xml_edi()
                    edi_doc._l10n_ec_action_check_xsd(xml_file)
                    xml_signed = company.l10n_ec_key_type_id.action_sign(xml_file)
                    _logger.debug(xml_signed)
                    if not attachment:
                        attachment = self.env["ir.attachment"].create(
                            {
                                "name": f"{edi_doc._l10n_ec_get_edi_name()}.xml",
                                "raw": xml_signed.encode(),
                                "res_model": document._name,
                                "res_id": document.id,
                                "mimetype": "application/xml",
                            }
                        )
                    else:
                        attachment.write(
                            {
                                "name": f"{edi_doc._l10n_ec_get_edi_name()}.xml",
                                "raw": xml_signed.encode(),
                                "res_model": document._name,
                                "res_id": document.id,
                                "mimetype": "application/xml",
                            }
                        )
                    if client_send is None or auth_client is None:
                        res.update(
                            {
                                document: {
                                    "success": False,
                                    "error": _(
                                        "Can't connect to SRI Webservice, try in few minutes"
                                    ),
                                    "attachment": attachment,
                                    "blocking_level": "error",
                                }
                            }
                        )
                        continue
                    # intentar consultar el documento previamente autorizado
                    is_sent = False
                    msj = []
                    if edi_doc.l10n_ec_last_sent_date:
                        sri_res = edi_doc._l10n_ec_edi_send_xml_auth(auth_client)
                        is_auth, msj = edi_doc._l10n_ec_edi_process_response_auth(
                            sri_res
                        )
                        errors.extend(msj)
                    if not is_auth:
                        sri_res = edi_doc._l10n_ec_edi_send_xml(client_send, xml_signed)
                        is_sent, msj = edi_doc._l10n_ec_edi_process_response_send(
                            sri_res
                        )
                        errors.extend(msj)
                    if not is_auth and is_sent and not msj:
                        # guardar la fecha de envio al SRI
                        # en caso de errores, poder saber si hubo un intento o no
                        # para antes de volver a enviarlo, consultar si se autorizo
                        edi_doc.write({"l10n_ec_last_sent_date": datetime.now()})
                        sri_res = edi_doc._l10n_ec_edi_send_xml_auth(auth_client)
                        is_auth, msj = edi_doc._l10n_ec_edi_process_response_auth(
                            sri_res
                        )
                        errors.extend(msj)
            except Exception as ex:
                _logger.error(tools.ustr(traceback.format_exc()))
                errors.append(
                    _(
                        "EDI Error creating xml file: %s",
                        tools.ustr(ex),
                    )
                )
            blocking_level = False
            if errors:
                blocking_level = "error"
            res.update(
                {
                    document: {
                        "success": True if not errors and is_auth else False,
                        "error": "".join(errors),
                        "attachment": attachment,
                        "blocking_level": blocking_level,
                    }
                }
            )
        return res

    @api.model
    def _l10n_ec_get_edi_ws_client(self, environment, url_type):
        """
        :param environment: tipo de ambiente, puede ser:
            test: Pruebas
            production: Produccion
        :param url_type: el tipo de url a solicitar, puede ser:
            reception: url para recepcion de documentos
            authorization: url para autorizacion de documentos
        :return:
        """
        # Debido a que el servidor esta rechazando las conexiones contantemente,
        # es necesario que se cree una sola instancia
        # Para conexion y asi evitar un reinicio constante de la comunicacion
        wsClient = None
        if environment == "test":
            ws_url = TEST_URL.get(url_type)
        elif environment == "production":
            ws_url = PRODUCTION_URL.get(url_type)
        try:
            transport = Transport(timeout=30)
            wsClient = Client(ws_url, transport=transport)
        except Exception as e:
            _logger.warning(
                "Error in Connection with web services of SRI: %s. Error: %s",
                ws_url,
                tools.ustr(e),
            )
        return wsClient
