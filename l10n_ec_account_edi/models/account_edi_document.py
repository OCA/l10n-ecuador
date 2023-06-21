import logging
import re
import traceback
from datetime import datetime
from os import path
from random import randint

import pytz
from lxml import etree
from zeep.helpers import serialize_object

from odoo import _, api, fields, models, tools
from odoo.exceptions import UserError
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT as DTF
from odoo.tools.misc import remove_accents

_logger = logging.getLogger(__name__)

EDI_DATE_FORMAT = "%d/%m/%Y"


class AccountEdiDocument(models.Model):
    _inherit = "account.edi.document"

    l10n_ec_xml_access_key = fields.Char(
        "Access Key(EC)", size=49, readonly=True, index=True
    )
    l10n_ec_authorization_date = fields.Datetime(
        "Authorization Date", readonly=True, index=True
    )
    l10n_ec_last_sent_date = fields.Datetime(
        "Last Sent Date", readonly=True, index=True
    )
    l10n_ec_document_number = fields.Char(
        string="Document Number", compute="_compute_l10n_ec_document_data", store=True
    )
    l10n_ec_document_date = fields.Date(
        store=True,
        string="Document Emission Date",
        compute="_compute_l10n_ec_document_data",
    )
    l10n_ec_partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Customer",
        compute="_compute_l10n_ec_document_data",
        store=True,
    )

    @api.depends("move_id")
    def _compute_l10n_ec_document_data(self):
        for edi_doc in self:
            edi_doc.l10n_ec_document_number = edi_doc._l10n_ec_get_edi_name()
            edi_doc.l10n_ec_document_date = edi_doc._l10n_ec_get_edi_date()
            document = edi_doc.l10n_ec_get_current_document()
            edi_doc.l10n_ec_partner_id = document.partner_id.id

    # funciones especificas para generacion de xml electronico
    @api.model
    def _l10n_ec_clean_str(self, str_to_clean):
        """
        Clean special characters
        :param str_to_clean: string to clean special characters
        :return str with  special characters removed
        """
        return re.sub("[^-A-Za-z0-9/?:().,'+ ]", "", remove_accents(str_to_clean))

    def _l10n_ec_header_get_document_lines_edi_data(self, taxes_data):
        res = []
        document_type = self.move_id.l10n_latam_internal_type
        for doc_line in self.move_id.invoice_line_ids.filtered(
            lambda x: not x.display_type
        ).sorted("price_subtotal"):
            line_tax_data = taxes_data.get("invoice_line_tax_details", {}).get(doc_line)
            if document_type == "invoice":
                res.append(doc_line.l10n_ec_get_invoice_edi_data(line_tax_data))
            if document_type == "purchase_liquidation":
                res.append(doc_line.l10n_ec_get_invoice_edi_data(line_tax_data))
            if document_type == "credit_note":
                res.append(doc_line.l10n_ec_get_credit_note_edi_data(line_tax_data))
            if document_type == "debit_note":
                res.append(doc_line.l10n_ec_get_debit_note_edi_data(line_tax_data))
            # TODO: agregar logica para demas tipos de documento
        return res

    def _l10n_ec_compute_amount_discount(self):
        self.ensure_one()
        return sum(
            (((line.discount * line.price_unit) * line.quantity) / 100.0)
            for line in self.move_id.invoice_line_ids
        )

    @api.model
    def _l10n_ec_prepare_tax_vals_edi(self, tax_data):
        tax = tax_data["tax"]
        base_amount = tax_data.get("base_amount_currency", 0.0)
        tax_amount = tax_data.get("tax_amount_currency", 0.0)
        rate = tax.amount
        tax_vals = {
            "codigo": tax.tax_group_id.l10n_ec_xml_fe_code,
            "codigoPorcentaje": tax.l10n_ec_xml_fe_code,
            "baseImponible": self._l10n_ec_number_format(abs(base_amount), 6),
            "tarifa": self._l10n_ec_number_format(abs(rate), 6),
            "valor": self._l10n_ec_number_format(abs(tax_amount), 6),
        }
        return tax_vals

    def l10n_ec_header_get_total_with_taxes(self, taxes_data):
        self.ensure_one()
        res = []
        for tax_data in taxes_data.get("tax_details", {}).values():
            tax_vals = self._l10n_ec_prepare_tax_vals_edi(tax_data)
            res.append(tax_vals)
        return res

    def _l10n_ec_get_environment(self):
        company = self.move_id.company_id or self.env.company
        # Si no esta configurado el campo, x defecto tomar pruebas
        res = "1"
        if company.l10n_ec_type_environment == "production":
            res = "2"
        return res

    @api.model
    def _l10n_ec_split_document_number(self, document_number, raise_error=False):
        """
        Split document number into entity_number, printer point and sequence
        :param document_number: str with format 001-001-0123456789
        :return tuple(entity_number, printer_point, sequence)
        """
        entity_number, printer_point, sequence_number = document_number.split("-")
        return (
            entity_number.rjust(3, "0"),
            printer_point.rjust(3, "0"),
            sequence_number.rjust(9, "0"),
        )

    def _l10n_ec_action_check_xsd(self, xml_string):
        try:
            xsd_file_path = self._l10n_ec_get_xsd_filename()
            xsd_file = tools.file_open(xsd_file_path)
            xmlschema_doc = etree.parse(xsd_file)
            xmlschema = etree.XMLSchema(xmlschema_doc)
            xml_doc = etree.fromstring(xml_string)
            result = xmlschema.validate(xml_doc)
            if not result:
                xmlschema.assert_(xml_doc)
            return result
        except AssertionError as e:
            if self.env.context.get("l10n_ec_xml_call_from_cron") or tools.config.get(
                "skip_xsd_check", False
            ):
                _logger.error(
                    "Wrong XML File, access_key: %s, Error: %s",
                    self.l10n_ec_xml_access_key,
                    tools.ustr(e),
                )
            else:
                raise UserError(
                    _("Wrong XML File, Detail: \n%s") % tools.ustr(e)
                ) from None
        return True

    def _l10n_ec_get_xsd_filename(self):
        filename = ""
        base_path = path.join("l10n_ec_account_edi", "data", "xsd")
        company = self.move_id.company_id or self.env.company
        document_type = self._l10n_ec_get_document_type()
        if document_type == "invoice":
            filename = f"factura_V{company.l10n_ec_invoice_version}"
        if document_type == "purchase_liquidation":
            filename = f"LiquidacionCompra_V{company.l10n_ec_liquidation_version}"
        if document_type == "credit_note":
            filename = f"NotaCredito_V{company.l10n_ec_credit_note_version}"
        if document_type == "debit_note":
            filename = f"NotaDebito_V{company.l10n_ec_debit_note_version}"
        # TODO: agregar logica para demas tipos de documento
        return path.join(base_path, f"{filename}.xsd")

    def _l10n_ec_get_info_tributaria(self, document):
        company = document.company_id
        document_code_sri = self._l10n_ec_get_edi_code_sri()
        (
            entity_number,
            printer_point_number,
            document_number,
        ) = self._l10n_ec_split_document_number(self._l10n_ec_get_edi_number())
        complete_document_number = (
            f"{entity_number}{printer_point_number}{document_number}"
        )
        journal = document.journal_id
        emission_address = (
            journal.l10n_ec_emission_address_id.commercial_partner_id.street
        )
        ruc = company.partner_id.vat
        environment = self._l10n_ec_get_environment()
        xml_access_key = self.l10n_ec_xml_access_key
        if not xml_access_key:
            # generar y guardar la clave de acceso
            xml_access_key = self.l10n_ec_generate_access_key(
                document_code_sri,
                complete_document_number,
                environment,
                self._l10n_ec_get_edi_date(),
                company,
            )
            self.l10n_ec_xml_access_key = xml_access_key
        social_name = "PRUEBAS SERVICIO DE RENTAS INTERNAS"
        business_name = "PRUEBAS SERVICIO DE RENTAS INTERNAS"
        if environment == "2":
            social_name = self._l10n_ec_clean_str(company.partner_id.name)
            business_name = self._l10n_ec_clean_str(
                company.partner_id.l10n_ec_business_name or social_name
            )
        data = {
            "ambiente": environment,
            "tipoEmision": "1",  # emision normal, SRI no acepta contingencia
            "razonSocial": social_name,
            "nombreComercial": business_name,
            "ruc": ruc,
            "claveAcceso": xml_access_key,
            "codDoc": document_code_sri,
            "estab": entity_number,
            "ptoEmi": printer_point_number,
            "secuencial": document_number,
            "dirMatriz": emission_address,
            "regimenMicroempresas": "",
            "agenteRetencion": company.l10n_ec_retention_agent,
            "contribuyenteRimpe": company.l10n_ec_get_regimen(),
            "company": company,
        }
        return data

    def _l10n_ec_get_document_type(self):
        document_type = self.move_id.l10n_latam_internal_type
        return document_type

    def l10n_ec_get_current_document(self):
        self.ensure_one()
        return self.move_id

    def _l10n_ec_get_edi_name(self):
        document = self.l10n_ec_get_current_document()
        edi_name = document._l10n_ec_get_document_name()
        return edi_name

    def _l10n_ec_get_edi_date(self):
        document = self.l10n_ec_get_current_document()
        edi_date = document._l10n_ec_get_document_date()
        return edi_date

    def _l10n_ec_get_edi_number(self):
        document = self.l10n_ec_get_current_document()
        edi_number = document.l10n_latam_document_number
        return edi_number

    def _l10n_ec_get_edi_code_sri(self):
        document = self.l10n_ec_get_current_document()
        edi_code = document._l10n_ec_get_document_code_sri()
        return edi_code

    @api.model
    def l10n_ec_generate_access_key(
        self,
        document_code_sri,
        complete_document_number,
        environment,
        date_document=None,
        company=None,
    ):
        """
        Generate access key according SRI technical data sheet(table 1)
        :param document_code_sri: code according SRI technical data sheet(table 1)
        :param complete_document_number: str with document number
            format(0010010123456789)
        :param: environment: 1=test; 2=production. see _l10n_ec_get_environment
        """
        if not company:
            company = self.env.company
        emission = "1"  # emision normal, ya no se admite contingencia(2)
        now_date = date_document.strftime("%d%m%Y")
        code_numeric = randint(1, 99999999)
        code_numeric = str(code_numeric).rjust(8, "0")
        access_key = (
            now_date
            + document_code_sri
            + company.partner_id.vat
            + environment
            + complete_document_number
            + code_numeric
            + emission
        )
        check_digit = self.l10n_ec_get_check_digit(access_key)
        return f"{access_key}{check_digit}"

    @api.model
    def l10n_ec_get_check_digit(self, access_key):
        """
        Compute verificator digit for access_key  according SRI technical data sheet(table 1)
        """
        mult = 1
        current_sum = 0
        for i in reversed(list(range(len(access_key)))):
            mult += 1
            if mult == 8:
                mult = 2
            current_sum += int(access_key[i]) * mult
        check_digit = 11 - (current_sum % 11)
        if check_digit == 11:
            check_digit = 0
        if check_digit == 10:
            check_digit = 1
        return check_digit

    @api.model
    def _l10n_ec_get_required_accounting(self, fiscal_position=None):
        res = "SI"
        if fiscal_position and fiscal_position.l10n_ec_no_account:
            res = "NO"
        return res

    @api.model
    def _l10n_ec_number_format(self, value, decimals=2):
        if isinstance(value, (int, float)):
            str_format = "{:." + str(decimals) + "f}"
            return str_format.format(value)
        else:
            return "0.00"

    def _l10n_ec_render_xml_edi(self):
        ViewModel = self.env["ir.ui.view"].sudo()
        document_type = self._l10n_ec_get_document_type()
        xml_file = ""
        if document_type == "invoice":
            xml_file = ViewModel._render_template(
                "l10n_ec_account_edi.ec_edi_invoice", self._l10n_ec_get_info_invoice()
            )
        if document_type == "purchase_liquidation":
            xml_file = ViewModel._render_template(
                "l10n_ec_account_edi.ec_edi_liquidation",
                self._l10n_ec_get_info_liquidation(),
            )
        if document_type == "credit_note":
            xml_file = ViewModel._render_template(
                "l10n_ec_account_edi.ec_edi_credit_note",
                self._l10n_ec_get_info_credit_note(),
            )
        if document_type == "debit_note":
            xml_file = ViewModel._render_template(
                "l10n_ec_account_edi.ec_edi_debit_note",
                self._l10n_ec_get_info_debit_note(),
            )
        # TODO: agregar logica para demas tipos de documento
        return xml_file

    def _l10n_ec_get_info_additional(self):
        additional_information = self.move_id.l10n_ec_additional_information_move_ids
        info_data = []

        for line in additional_information:
            info_data.append(
                {
                    "name": line.name,
                    "description": line.description,
                }
            )
        return info_data

    def _l10n_ec_get_info_invoice(self):
        self.ensure_one()
        invoice = self.move_id
        date_invoice = invoice.invoice_date
        company = invoice.company_id or self.env.company
        taxes_data = invoice._l10n_ec_get_taxes_grouped_by_tax_group()
        amount_total = abs(taxes_data.get("base_amount") + taxes_data.get("tax_amount"))
        currency = invoice.currency_id
        currency_name = currency.name or "DOLAR"
        invoice_data = {
            "fechaEmision": (date_invoice).strftime(EDI_DATE_FORMAT),
            "dirEstablecimiento": self._l10n_ec_clean_str(
                invoice.journal_id.l10n_ec_emission_address_id.street or ""
            )[:300],
            "contribuyenteEspecial": company.l10n_ec_get_resolution_data(date_invoice),
            "obligadoContabilidad": self._l10n_ec_get_required_accounting(
                company.partner_id.property_account_position_id
            ),
            "tipoIdentificacionComprador": invoice._get_l10n_ec_identification_type(),
            "razonSocialComprador": self._l10n_ec_clean_str(
                invoice.commercial_partner_id.name
            )[:300],
            "identificacionComprador": invoice.commercial_partner_id.vat,
            "direccionComprador": self._l10n_ec_clean_str(
                invoice.commercial_partner_id.street or "NA"
            )[:300],
            "totalSinImpuestos": self._l10n_ec_number_format(invoice.amount_untaxed, 6),
            "totalDescuento": self._l10n_ec_number_format(
                self._l10n_ec_compute_amount_discount(), 6
            ),
            "totalConImpuestos": self.l10n_ec_header_get_total_with_taxes(taxes_data),
            "compensaciones": [],
            "propina": False,
            "importeTotal": self._l10n_ec_number_format(amount_total, 6),
            "moneda": currency_name,
            "pagos": invoice._l10n_ec_get_payment_data(),
            "valorRetIva": False,
            "valorRetRenta": False,
            "detalles": self._l10n_ec_header_get_document_lines_edi_data(taxes_data),
            "retenciones": False,
            "infoSustitutivaGuiaRemision": False,
            "infoAdicional": self._l10n_ec_get_info_additional(),
        }
        invoice_data.update(self._l10n_ec_get_info_tributaria(invoice))
        return invoice_data

    def _l10n_ec_get_info_liquidation(self):
        self.ensure_one()
        invoice = self.move_id
        date_invoice = invoice.invoice_date
        company = invoice.company_id or self.env.company
        taxes_data = invoice._l10n_ec_get_taxes_grouped_by_tax_group()
        amount_total = abs(taxes_data.get("base_amount") + taxes_data.get("tax_amount"))
        currency = invoice.currency_id
        currency_name = currency.name or "DOLAR"
        invoice_data = {
            "fechaEmision": (date_invoice).strftime(EDI_DATE_FORMAT),
            "dirEstablecimiento": self._l10n_ec_clean_str(
                invoice.journal_id.l10n_ec_emission_address_id.street or ""
            )[:300],
            "contribuyenteEspecial": company.l10n_ec_get_resolution_data(date_invoice),
            "obligadoContabilidad": self._l10n_ec_get_required_accounting(
                company.partner_id.property_account_position_id
            ),
            "tipoIdentificacionProveedor": invoice.l10n_ec_get_identification_type(),
            "razonSocialProveedor": self._l10n_ec_clean_str(
                invoice.commercial_partner_id.name
            )[:300],
            "identificacionProveedor": (invoice.commercial_partner_id.vat or "NA"),
            "direccionProveedor": self._l10n_ec_clean_str(
                invoice.commercial_partner_id.street or "NA"
            )[:300],
            "totalSinImpuestos": self._l10n_ec_number_format(invoice.amount_untaxed, 6),
            "totalDescuento": self._l10n_ec_number_format(
                self._l10n_ec_compute_amount_discount(), 6
            ),
            "totalConImpuestos": self.l10n_ec_header_get_total_with_taxes(taxes_data),
            "compensaciones": [],
            "importeTotal": self._l10n_ec_number_format(amount_total, 6),
            "moneda": currency_name,
            "pagos": invoice._l10n_ec_get_payment_data(),
            "valorRetIva": False,
            "valorRetRenta": False,
            "detalles": self._l10n_ec_header_get_document_lines_edi_data(taxes_data),
            "retenciones": False,
            "infoAdicional": self._l10n_ec_get_info_additional(),
        }
        invoice_data.update(self._l10n_ec_get_info_tributaria(invoice))
        return invoice_data

    def _l10n_ec_get_info_credit_note(self):
        self.ensure_one()
        credit_note = self.move_id
        date_invoice = credit_note.invoice_date
        company = credit_note.company_id or self.env.company
        taxes_data = credit_note._l10n_ec_get_taxes_grouped_by_tax_group()
        amount_total = abs(taxes_data.get("base_amount") + taxes_data.get("tax_amount"))
        currency = credit_note.currency_id
        currency_name = currency.name or "DOLAR"
        credit_note_data = {
            "fechaEmision": (date_invoice).strftime(EDI_DATE_FORMAT),
            "dirEstablecimiento": self._l10n_ec_clean_str(
                credit_note.journal_id.l10n_ec_emission_address_id.street or ""
            )[:300],
            "contribuyenteEspecial": company.l10n_ec_get_resolution_data(date_invoice),
            "obligadoContabilidad": self._l10n_ec_get_required_accounting(
                company.partner_id.property_account_position_id
            ),
            "codDocModificado": "01",
            "numDocModificado": credit_note.l10n_ec_legacy_document_number,
            "fechaEmisionDocSustento": (
                credit_note.l10n_ec_legacy_document_date
            ).strftime(EDI_DATE_FORMAT),
            "motivo": credit_note.l10n_ec_reason,
            "tipoIdentificacionComprador": credit_note._get_l10n_ec_identification_type(),
            "razonSocialComprador": self._l10n_ec_clean_str(
                credit_note.commercial_partner_id.name
            )[:300],
            "identificacionComprador": credit_note.commercial_partner_id.vat,
            # TODO YRO revisar en ficha tecnica no lo esta pidiendo
            "direccionComprador": self._l10n_ec_clean_str(
                credit_note.commercial_partner_id.street or "NA"
            )[:300],
            "totalSinImpuestos": self._l10n_ec_number_format(
                credit_note.amount_untaxed, 6
            ),
            "totalDescuento": self._l10n_ec_number_format(
                self._l10n_ec_compute_amount_discount(), 6
            ),
            "totalConImpuestos": self.l10n_ec_header_get_total_with_taxes(taxes_data),
            "compensaciones": [],
            "propina": False,
            "importeTotal": self._l10n_ec_number_format(amount_total, 6),
            "valorModificacion": self._l10n_ec_number_format(amount_total, 6),
            "moneda": currency_name,
            "pagos": credit_note._l10n_ec_get_payment_data(),
            "valorRetIva": False,
            "valorRetRenta": False,
            "detalles": self._l10n_ec_header_get_document_lines_edi_data(taxes_data),
            "retenciones": False,
            "infoSustitutivaGuiaRemision": False,
            "infoAdicional": self._l10n_ec_get_info_additional(),
        }
        credit_note_data.update(self._l10n_ec_get_info_tributaria(credit_note))
        return credit_note_data

    def _l10n_ec_edi_send_xml(self, client_ws, xml_file):
        """
        Enviar a validar el comprobante con la clave de acceso
        :param client_ws: instancia del webservice para realizar el proceso
        """
        response = {}
        try:
            # el parametro xml del webservice espera recibir xs:base64Binary
            # con suds nosotros haciamos la conversion
            # pero con zeep la libreria se encarga de hacer la conversion
            # tenerlo presente cuando se use adjuntos en lugar del sistema de archivos
            response = client_ws.service.validarComprobante(xml=xml_file.encode())
            _logger.info(
                "Send file succesful, claveAcceso %s. %s",
                self.l10n_ec_xml_access_key,
                getattr(response, "estado", "SIN RESPUESTA"),
            )
        except Exception as e:
            _logger.info(
                "can't validate document in %s, claveAcceso %s. ERROR: %s TRACEBACK: %s",
                str(client_ws),
                self.l10n_ec_xml_access_key,
                tools.ustr(e),
                tools.ustr(traceback.format_exc()),
            )
        return response

    def _l10n_ec_edi_process_response_send(self, response):
        """
        Procesa la respuesta del webservice
        si fue devuelta, devolver False los mensajes
        si fue recibida, devolver True y los mensajes
        """
        msj_list = []
        response_data = serialize_object(response, dict)

        try:
            ok = response_data.get("estado", "") == "RECIBIDA"
            if response_data.get("estado", "") == "DEVUELTA":
                # si fue devuelta intentar nuevamente
                ok = False
            comprobantes = (response_data.get("comprobantes") or {}).get(
                "comprobante"
            ) or []
            for comprobante in comprobantes:
                mensajes = (comprobante.get("mensajes") or {}).get("mensaje") or []
                for msj in mensajes:
                    if msj.get("tipo") == "ERROR":
                        ok = False
                    msj_str = "%s [%s] %s %s" % (
                        msj.get("tipo") or "",
                        msj.get("identificador") or "",
                        msj.get("mensaje") or "",
                        msj.get("informacionAdicional") or "",
                    )
                    msj_list.append(msj_str)
        except Exception as e:
            msj_list.append(tools.ustr(e))
            _logger.info(
                "can't validate document, clave de acceso %s. ERROR: %s TRACEBACK: %s",
                self.l10n_ec_xml_access_key,
                tools.ustr(e),
                tools.ustr(traceback.format_exc()),
            )
            ok = False
        return ok, msj_list

    def _l10n_ec_edi_send_xml_auth(self, client_ws):
        """
        Envia a autorizar el archivo
        :param client_ws: direccion del webservice para realizar el proceso
        """
        try:
            response = client_ws.service.autorizacionComprobante(
                claveAccesoComprobante=self.l10n_ec_xml_access_key
            )
        except Exception as e:
            response = False
            _logger.warning(
                "Error send xml to server %s. ERROR: %s", client_ws, tools.ustr(e)
            )
        return response

    def _l10n_ec_edi_process_response_auth(self, response):
        """
        Procesa la respuesta del webservice
        si fue devuelta, devolver False los mensajes
        si fue recibida, devolver True y los mensajes
        """
        is_auth = False
        msj_list = []
        response_data = serialize_object(response, dict)
        if not response_data or not response_data.get("autorizaciones"):
            _logger.warning("Authorization response error, No Autorizacion in response")
            return is_auth, msj_list
        # a veces el SRI devulve varias autorizaciones, unas como no autorizadas
        # pero otra si autorizada, si pasa eso, tomar la que fue autorizada
        # las demas ignorarlas
        autorizacion_list = response_data.get("autorizaciones").get("autorizacion")
        if not isinstance(autorizacion_list, list):
            autorizacion_list = [autorizacion_list]
        for doc in autorizacion_list:
            mensajes = (doc.get("mensajes") or {}).get("mensaje") or []
            for msj in mensajes:
                msj_str = "%s [%s] %s %s" % (
                    msj.get("tipo") or "",
                    msj.get("identificador") or "",
                    msj.get("mensaje") or "",
                    msj.get("informacionAdicional") or "",
                )
                msj_list.append(msj_str)
            estado = doc.get("estado")
            if estado != "AUTORIZADO":
                is_auth = False
                continue
            is_auth = True
            msj_list = []
            # tomar la fecha de autorizacion que envia el SRI
            l10n_ec_authorization_date = doc.get("fechaAutorizacion")
            # si no es una fecha valida, tomar la fecha actual del sistema
            if not isinstance(l10n_ec_authorization_date, datetime):
                l10n_ec_authorization_date = datetime.now()
            if l10n_ec_authorization_date.tzinfo:
                l10n_ec_authorization_date = l10n_ec_authorization_date.astimezone(
                    pytz.UTC
                )
            _logger.info(
                "Authorization succesful, claveAcceso %s. Fecha de autorizacion: %s",
                self.l10n_ec_xml_access_key,
                l10n_ec_authorization_date,
            )
            self.write(
                {"l10n_ec_authorization_date": l10n_ec_authorization_date.strftime(DTF)}
            )
            break
        return is_auth, msj_list

    def _l10n_ec_get_info_debit_note(self):
        self.ensure_one()
        debit_note = self.move_id
        company = debit_note.company_id or self.env.company
        date_debit = debit_note.invoice_date
        taxes_data = debit_note._l10n_ec_get_taxes_grouped_by_tax_group()
        amount_total = abs(taxes_data.get("base_amount") + taxes_data.get("tax_amount"))

        debit_note_dict = {
            "fechaEmision": date_debit.strftime(EDI_DATE_FORMAT),
            "dirEstablecimiento": self._l10n_ec_clean_str(
                debit_note.journal_id.l10n_ec_emission_address_id.street or ""
            )[:300],
            "contribuyenteEspecial": company.l10n_ec_get_resolution_data(None),
            "obligadoContabilidad": self._l10n_ec_get_required_accounting(
                company.partner_id.property_account_position_id
            ),
            # Customer data
            "tipoIdentificacionComprador": debit_note.l10n_ec_get_identification_type(),
            "razonSocialComprador": self._l10n_ec_clean_str(
                debit_note.commercial_partner_id.name
            )[:300],
            "identificacionComprador": debit_note.commercial_partner_id.vat,
            # Debit Note data
            "codDocModificado": "01",
            "numDocModificado": debit_note.l10n_ec_legacy_document_number,
            "fechaEmisionDocSustento": debit_note.l10n_ec_legacy_document_date.strftime(
                EDI_DATE_FORMAT
            ),
            "totalSinImpuestos": self._l10n_ec_number_format(
                debit_note.amount_untaxed, 6
            ),
            "totalConImpuestos": self.l10n_ec_header_get_total_with_taxes(taxes_data),
            "importeTotal": self._l10n_ec_number_format(amount_total, 6),
            "pagos": debit_note._l10n_ec_get_payment_data(),
            "detalles": self._l10n_ec_header_get_document_lines_edi_data(taxes_data),
            "infoAdicional": self._l10n_ec_get_info_additional(),
        }

        debit_note_dict.update(self._l10n_ec_get_info_tributaria(debit_note))
        return debit_note_dict

    @api.model
    def l10n_ec_send_mail_to_partners(self):
        all_companies = self.env["res.company"].search(
            [
                ("partner_id.country_id.code", "=", "EC"),
                ("l10n_ec_type_environment", "=", "production"),
            ]
        )
        for company in all_companies:
            self.with_company(company).l10n_ec_send_mail_to_partner()
        return True

    @api.model
    def l10n_ec_send_mail_to_partner(self):
        commom_domain = [
            ("state", "=", "posted"),
            ("is_move_sent", "=", False),
            ("l10n_ec_authorization_date", "!=", False),
        ]
        account_moves = self.env["account.move"].search(
            commom_domain
            + [
                ("partner_id.vat", "not in", ["9999999999999", "9999999999"]),
            ]
        )
        for account_move in account_moves:
            account_move.l10n_ec_send_email()

        # Update documents with final consumer
        account_moves_with_final_consumer = self.env["account.move"].search(
            commom_domain
            + [
                ("partner_id.vat", "in", ["9999999999999", "9999999999"]),
            ]
        )
        account_moves_with_final_consumer.write({"is_move_sent": True})
