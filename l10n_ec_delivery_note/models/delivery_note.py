import logging
from datetime import datetime
from os import path

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.translate import _

EDI_DATE_FORMAT = "%d/%m/%Y"
_logger = logging.getLogger(__name__)


class DeliveryNote(models.Model):
    _inherit = ["mail.thread", "mail.activity.mixin", "portal.mixin", "sequence.mixin"]
    _name = "l10n_ec.delivery.note"
    _description = "Delivery Note"
    _rec_name = "document_number"

    _sequence_field = "document_number"
    _sequence_date_field = "transfer_date"

    document_number = fields.Char(
        size=20,
        readonly=True,
        index=True,
        tracking=True,
        compute="_compute_document_number",
        store=True,
    )
    journal_id = fields.Many2one(
        comodel_name="account.journal",
        string="Emission Point",
        check_company=True,
        domain=[("l10n_latam_use_documents", "=", True), ("type", "=", "sale")],
    )
    transfer_date = fields.Date(
        required=True,
        default=lambda self: fields.Date.context_today(self),
        tracking=True,
    )
    delivery_date = fields.Date(
        required=True,
        default=lambda self: fields.Date.context_today(self),
        tracking=True,
    )
    motive = fields.Text(copy=False)
    l10n_ec_car_plate = fields.Char("Car plate", size=8, required=False)
    stock_picking_ids = fields.Many2many(
        "stock.picking",
        string="Pickings related",
        copy=False,
    )
    sale_order_ids = fields.Many2many(
        "sale.order",
        "sale_order_delivery_note_rel",
        "delivery_note_id",
        "order_id",
        "Sales Order",
        readonly=True,
        copy=False,
    )
    partner_id = fields.Many2one(
        "res.partner",
        "Partner",
        index=True,
        auto_join=True,
        tracking=True,
    )
    commercial_partner_id = fields.Many2one(
        "res.partner",
        string="Commercial Entity",
        compute_sudo=True,
        related="partner_id.commercial_partner_id",
        store=True,
        readonly=True,
        help="The commercial entity that will be used for this delivery note",
    )
    delivery_address_id = fields.Many2one(
        "res.partner",
        "Delivery Address",
        index=True,
        tracking=True,
    )
    delivery_carrier_id = fields.Many2one(
        "res.partner",
        "Delivery Carrier",
        index=True,
        domain=[("l10n_ec_is_carrier", "=", True)],
    )
    delivery_note_type = fields.Selection(
        [
            ("sales", "Transfer by Sales"),
            ("internal", "Internal Transfer"),
        ],
        default="sales",
    )
    delivery_line_ids = fields.One2many(
        "l10n_ec.delivery.note.line",
        "delivery_note_id",
        "Delivery note detail",
        copy=True,
        auto_join=True,
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("done", "Done"),
            ("cancel", "Cancel"),
        ],
        index=True,
        required=True,
        readonly=True,
        default="draft",
        tracking=True,
    )
    company_id = fields.Many2one(
        "res.company",
        "Company",
        default=lambda self: self.env.company,
        required=True,
    )
    country_code = fields.Char(
        related="company_id.account_fiscal_country_id.code", readonly=True
    )
    rise = fields.Char("R.I.S.E", copy=False)
    dau = fields.Char("D.A.U.", copy=False)
    note = fields.Text(string="Notes", copy=False)
    origin = fields.Text(copy=False)
    invoice_id = fields.Many2one("account.move", string="Invoice")

    edi_state = fields.Selection(
        selection=[
            ("to_send", "To Send"),
            ("sent", "Sent"),
            ("to_cancel", "To Cancel"),
            ("cancelled", "Cancelled"),
        ],
        string="Electronic invoicing",
        store=True,
        help="The aggregated state of all the EDIs with web-service of this move",
    )

    edi_error_count = fields.Integer(
        help="How many EDIs are in error for this move ?",
    )
    edi_blocking_level = fields.Selection(
        selection=[("info", "Info"), ("warning", "Warning"), ("error", "Error")]
    )
    edi_error_message = fields.Html()

    edi_web_services_to_process = fields.Text(
        help="Technical field to display the documents that "
        "will be processed by the CRON",
    )
    l10n_ec_authorization_date = fields.Datetime(
        string="Access Key(EC)",
        store=True,
    )
    l10n_ec_xml_access_key = fields.Char(
        string="Electronic Authorization Date",
        store=True,
    )
    l10n_ec_is_edi_doc = fields.Boolean(
        string="Is Ecuadorian Electronic Document", default=False, copy=False
    )

    is_delivery_note_sent = fields.Boolean(default=False)

    l10n_ec_last_sent_date = fields.Datetime(
        "Last Sent Date", readonly=True, index=True
    )

    @api.depends("journal_id")
    def _compute_document_number(self):
        self.filtered(
            lambda x: not x.document_number
            or x.document_number
            and x.journal_id.l10n_latam_use_documents
            and x.state == "draft"
        ).document_number = "/"
        for rec in self.filtered(lambda x: x.journal_id):
            rec._set_next_sequence()

    @api.constrains("transfer_date", "delivery_date")
    def _check_transfer_dates(self):
        for delivery in self:
            if (
                delivery.transfer_date
                and delivery.delivery_date
                and delivery.delivery_date < delivery.transfer_date
            ):
                raise ValidationError(
                    _("The Delivery Date can't less than transfer date, please check")
                )

    @api.constrains("transfer_date")
    def _check_transfer_date(self):
        for delivery in self:
            date_current = fields.Date.context_today(self)
            if delivery.transfer_date and delivery.transfer_date > date_current:
                raise UserError(
                    _(
                        "You cannot create the delivery note electronic %s "
                        "with a date later than the current one"
                    )
                    % delivery.document_number
                )

    @api.onchange("stock_picking_ids")
    def _onchange_stock_picking_ids(self):
        rline_model = self.env["l10n_ec.delivery.note.line"]
        for delivery_note in self:
            new_lines = rline_model.browse()
            # si tengo picking tomar datos,
            # asi no se consideraria la factura en caso de tenerla
            if delivery_note.stock_picking_ids:
                main_picking = delivery_note.stock_picking_ids[0]
                for picking in delivery_note.stock_picking_ids:
                    for move in picking.move_line_ids:
                        new_lines += rline_model.new(
                            rline_model._prepare_delivery_note_line(delivery_note, move)
                        )
                if not delivery_note.partner_id and main_picking.partner_id:
                    delivery_note.partner_id = main_picking.partner_id.id
                if (
                    not delivery_note.delivery_carrier_id
                    and main_picking.l10n_ec_delivery_carrier_id
                ):
                    delivery_note.delivery_carrier_id = (
                        main_picking.l10n_ec_delivery_carrier_id.id
                    )
                if (
                    not delivery_note.journal_id
                    and main_picking.l10n_ec_delivery_note_journal_id
                ):
                    delivery_note.journal_id = (
                        main_picking.l10n_ec_delivery_note_journal_id.id
                    )
            self.delivery_line_ids = new_lines

    @api.onchange(
        "delivery_carrier_id",
    )
    def onchange_carrier_id(self):
        self.l10n_ec_car_plate = (
            self.delivery_carrier_id
            and self.delivery_carrier_id.l10n_ec_car_plate
            or ""
        )

    @api.onchange("partner_id")
    def onchange_partner_id(self):
        if self.partner_id:
            addr = self.partner_id.address_get(["delivery"])
            self.delivery_address_id = addr["delivery"]

    _sql_constraints = [
        (
            "document_number_uniq",
            "unique(document_number, company_id)",
            _(
                "Document number of Delivery Note must be Unique by company, "
                "please check"
            ),
        )
    ]

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)

        return defaults

    def unlink(self):
        for delivery_note in self:
            if delivery_note.state != "draft":
                raise UserError(_("Cant'n unlink Delivery Note, Try cancel!"))
        return super().unlink()

    def action_confirm(self):
        for delivery_note in self:
            errors = self._l10n_ec_check_delivery_note_configuration(delivery_note)
            if errors:
                raise UserError(
                    _("Invalid delivery note configuration:\n\n%s") % "\n".join(errors)
                )

            if not delivery_note.delivery_line_ids and not self.env.context.get(
                "force_approve", False
            ):
                raise UserError(_("You must be enter at least a line, please verify"))
            for picking in delivery_note.stock_picking_ids:
                if picking.sale_id:
                    if (
                        delivery_note.id
                        not in picking.sale_id.l10n_ec_delivery_note_ids.ids
                    ):
                        picking.sale_id.write(
                            {"l10n_ec_delivery_note_ids": [(4, delivery_note.id)]}
                        )
            delivery_note.write({"state": "done"})
            delivery_note._l10n_ec_create_edi_document()
        return True

    def action_cancel(self):
        return self.write({"state": "cancel"})

    def action_set_draft(self):
        return self.write({"state": "draft"})

    def _get_last_sequence_domain(self, relaxed=False):
        self.ensure_one()
        where_string = "WHERE journal_id = %(journal_id)s AND document_number != '/'"
        param = {"journal_id": self.journal_id.id}
        return where_string, param

    def _get_ec_formatted_sequence(self, number=0):
        return "%s-%s-%09d" % (
            self.journal_id.l10n_ec_entity,
            self.journal_id.l10n_ec_emission,
            number,
        )

    def _get_starting_sequence(self):
        """If use documents then will create a new starting sequence
        using the document type code prefix and the
        journal document number with a 8 padding number"""
        if (
            self.journal_id.l10n_latam_use_documents
            and self.company_id.country_id.code == "EC"
        ):
            return self._get_ec_formatted_sequence()
        return super()._get_starting_sequence()

    def _l10n_ec_get_document_date(self):
        return self.transfer_date

    def _l10n_ec_get_document_code_sri(self):
        return "06"

    def _l10n_ec_get_document_name(self):
        return "GR %s" % self.display_name

    def _l10n_ec_create_edi_document(self):
        # Set the electronic document to be posted and post immediately
        # for synchronous formats.
        self.ensure_one()

        self.write({"edi_state": "to_send", "l10n_ec_is_edi_doc": True})

        xml_file = self._l10n_ec_render_xml_edi()
        edi_document = self.env["account.edi.document"]

        base_path = path.join("l10n_ec_delivery_note", "data", "xsd")
        company = self.env.company
        filename = f"GuiaRemision_V{company.l10n_ec_delivery_note_version}"

        try:
            edi_document._l10n_ec_action_check_xsd(
                xml_file, path.join(base_path, f"{filename}.xsd")
            )
        except Exception as error:
            _logger.debug(error)
            self.write(
                {
                    "edi_error_message": error,
                    "edi_blocking_level": "error",
                }
            )
            return self

        _logger.debug(xml_file)
        xml_signed = self.company_id.l10n_ec_key_type_id.action_sign(xml_file)

        attachment = self.env["ir.attachment"].search(
            [
                ("res_model", "=", self._name),
                ("res_id", "=", self.id),
                ("name", "=", f"GR-{self.document_number}.xml"),
            ]
        )

        if not attachment:
            self.env["ir.attachment"].create(
                {
                    "name": f"GR-{self.document_number}.xml",
                    "raw": xml_signed.encode(),
                    "res_model": self._name,
                    "res_id": self.id,
                    "mimetype": "application/xml",
                }
            )
        else:
            attachment.write({"raw": xml_signed.encode()})

        edi_format = self.env["account.edi.format"]
        client_send = edi_format._l10n_ec_get_edi_ws_client(
            self.company_id.l10n_ec_type_environment, "reception"
        )
        auth_client = edi_format._l10n_ec_get_edi_ws_client(
            self.company_id.l10n_ec_type_environment, "authorization"
        )

        if client_send is None or auth_client is None:
            self.write(
                {
                    "edi_error_message": _(
                        "Can't connect to SRI web service, try again later"
                    ),
                    "edi_blocking_level": "error",
                }
            )
            return self

        # intentar consultar el documento previamente autorizado

        is_auth = False
        is_sent = False
        msj = []
        errors = []
        authorization_date = False
        if self.l10n_ec_last_sent_date:
            sri_res = edi_document._l10n_ec_edi_send_xml_auth(auth_client)
            (
                is_auth,
                msj,
                authorization_date,
            ) = edi_document._l10n_ec_edi_process_response_auth(sri_res)
            errors.extend(msj)
        if not is_auth:
            sri_res = edi_document._l10n_ec_edi_send_xml(client_send, xml_signed)
            is_sent, msj = edi_document._l10n_ec_edi_process_response_send(sri_res)
            errors.extend(msj)
        if not is_auth and is_sent and not msj:
            # guardar la fecha de envio al SRI
            # en caso de errores, poder saber si hubo un intento o no
            # para antes de volver a enviarlo, consultar si se autorizo
            sri_res = edi_document._l10n_ec_edi_send_xml_auth(
                auth_client, self.l10n_ec_xml_access_key
            )
            (
                is_auth,
                msj,
                authorization_date,
            ) = edi_document._l10n_ec_edi_process_response_auth(sri_res)
            errors.extend(msj)

        if errors:
            self.edi_blocking_level = "error"

        if is_auth:
            self.write(
                {
                    "edi_state": "sent",
                    "l10n_ec_is_edi_doc": True,
                    "l10n_ec_authorization_date": authorization_date,
                }
            )
        else:
            self.write(
                {
                    "edi_error_message": "\n".join(errors),
                    "edi_blocking_level": "error",
                }
            )

        self.l10n_ec_last_sent_date = datetime.now()
        return self

    # Métodos del portal
    def _compute_access_url(self):
        res = super()._compute_access_url()
        for delivery_note in self:
            delivery_note.access_url = "/my/edi_delivery_note/%s" % (delivery_note.id)
        return res

    def _get_report_base_filename(self):
        self.ensure_one()
        return f"GR-{self.document_number}"

    def action_sent_mail_electronic(self):
        # funcion para levantar asistente para renderizar plantilla
        # y usuario pueda enviar correo manualmente
        self.ensure_one()
        template = self.env.ref(
            "l10n_ec_delivery_note.email_template_e_delivery_note", False
        )
        ctx = {
            "default_model": self._name,
            "active_ids": self.ids,
            "default_use_template": bool(template),
            "default_template_id": template.id,
            "default_composition_mode": "comment",
            "custom_layout": "mail.mail_notification_light",
            "force_email": True,
            "model_description": _("Delivery Note"),
        }
        return {
            "type": "ir.actions.act_window",
            "view_mode": "form",
            "res_model": "mail.compose.message",
            "views": [(False, "form")],
            "view_id": False,
            "target": "new",
            "context": ctx,
        }

    def l10n_ec_action_sent_mail_electronic(self):
        """
        Funcion para enviar correo automaticamente desde un cron
        """
        mail_compose_model = self.env["mail.compose.message"]
        action = self.action_sent_mail_electronic()
        ctx = action.get("context")
        msj = mail_compose_model.with_context(**ctx).create({})
        send_mail = True
        try:
            msj._onchange_template_id_wrapper()
            msj._action_send_mail()
        except Exception:
            send_mail = False
        return send_mail

    def _l10n_ec_check_delivery_note_configuration(self, document):
        company = document.company_id
        partner = document.commercial_partner_id
        errors = self.env["account.edi.format"]._l10n_ec_check_edi_configuration(
            document, company
        )
        # ruc en transportista
        if not document.delivery_carrier_id.vat:
            errors.append(
                _(
                    "You must set vat identification for carrier: %s",
                    document.delivery_carrier_id.name,
                )
            )
        if not document.delivery_address_id.street:
            errors.append(
                _(
                    "You must set delivery address for receiver: %s",
                    document.delivery_address_id.commercial_partner_id.name,
                )
            )
        if not company.l10n_ec_delivery_note_version:
            errors.append(
                _(
                    "You must set XML Version for Delivery Note company %s",
                    company.display_name,
                )
            )
        error_identification = self._check_l10n_ec_values_identification_type(partner)
        if error_identification:
            errors.extend(error_identification)

        return errors

    def _check_l10n_ec_values_identification_type(self, partner):
        ec_ruc = self.env.ref("l10n_ec.ec_ruc", False)
        ec_dni = self.env.ref("l10n_ec.ec_dni", False)
        ec_passport = self.env.ref("l10n_ec.ec_passport", False)
        errors = []
        # validar que la empresa tenga ruc y tipo de documento
        if not partner.vat:
            errors.append(_("Please enter DNI/RUC to partner: %s", partner.name))
        if partner.l10n_latam_identification_type_id.id not in (
            ec_ruc.id,
            ec_dni.id,
            ec_passport.id,
        ):
            errors.append(
                _(
                    "You must set Identification type as RUC, DNI or Passport "
                    "for ecuadorian company, on partner %s",
                    partner.name,
                )
            )
        return errors

    @api.model
    def l10n_ec_get_type_identification(self, number):
        if len(number) == 10:
            return "05"
        elif len(number) == 13:
            return "04"

    def _l10n_ec_render_xml_edi(self):
        xml_access_key = self.l10n_ec_xml_access_key
        if not xml_access_key:
            # generar y guardar la clave de acceso
            account_edi_document = self.env["account.edi.document"]
            (
                entity_number,
                printer_point_number,
                document_number,
            ) = account_edi_document._l10n_ec_split_document_number(
                self.document_number
            )
            environment = account_edi_document._l10n_ec_get_environment()
            document_code_sri = self._l10n_ec_get_document_code_sri()
            xml_access_key = account_edi_document.l10n_ec_generate_access_key(
                document_code_sri,
                f"{entity_number}{printer_point_number}{document_number}",
                environment,
                self._l10n_ec_get_document_date(),
                self.company_id,
            )
            self.l10n_ec_xml_access_key = xml_access_key

        ViewModel = self.env["ir.ui.view"].sudo()
        xml_file = ViewModel._render_template(
            "l10n_ec_delivery_note.l10n_ec_delivery_note",
            self._l10n_ec_get_info_delivery_note(xml_access_key),
        )
        return xml_file

    def _l10n_ec_get_info_delivery_note(self, xml_access_key: str):
        edi = self.env["account.edi.document"]
        delivery_note = self
        invoice = True if delivery_note.invoice_id else False
        company = self.company_id
        address = (
            delivery_note.delivery_address_id
            and delivery_note.delivery_address_id.street
            or "NA"
        )
        delivery_note_data = {
            "dirEstablecimiento": edi._l10n_ec_clean_str(
                delivery_note.journal_id.l10n_ec_emission_address_id.street or ""
            )[:300],
            "dirPartida": edi._l10n_ec_clean_str(
                delivery_note.journal_id.l10n_ec_emission_address_id.street or ""
            )[:300],
            "razonSocialTransportista": edi._l10n_ec_clean_str(
                delivery_note.delivery_carrier_id.name
            )[:300],
            "tipoIdentificacionTransportista": delivery_note.l10n_ec_get_type_identification(  # noqa
                delivery_note.delivery_carrier_id.vat
            ),
            "rucTransportista": delivery_note.delivery_carrier_id.vat,
            "rise": delivery_note.rise if delivery_note.rise else False,
            "obligadoContabilidad": edi._l10n_ec_get_required_accounting(
                company.partner_id.property_account_position_id
            ),
            "contribuyenteEspecial": delivery_note.company_id.l10n_ec_get_resolution_data(  # noqa
                delivery_note.transfer_date
            ),
            "fechaIniTransporte": delivery_note.transfer_date.strftime(EDI_DATE_FORMAT),
            "fechaFinTransporte": delivery_note.delivery_date.strftime(EDI_DATE_FORMAT),
            "placa": delivery_note.l10n_ec_car_plate or "N/A",
            "identificacionDestinatario": delivery_note.partner_id.commercial_partner_id.vat,  # noqa
            "razonSocialDestinatario": edi._l10n_ec_clean_str(
                delivery_note.partner_id.commercial_partner_id.name
            )[:300],
            "dirDestinatario": edi._l10n_ec_clean_str(address)[:300],
            "motivoTraslado": edi._l10n_ec_clean_str(delivery_note.motive or "N/A")[
                :300
            ],
            "docAduaneroUnico": delivery_note.dau if delivery_note.dau else False,
            "invoice": invoice,
            "codDocSustento": "01" if invoice else False,
            "numDocSustento": delivery_note.invoice_id.l10n_latam_document_number
            if invoice
            else False,
            "numAutDocSustento": self.l10n_ec_xml_access_key if invoice else False,
            "fechaEmisionDocSustento": delivery_note.invoice_id.invoice_date.strftime(
                EDI_DATE_FORMAT
            )
            if invoice
            else False,
            "detalles": self._l10n_ec_get_details_delivery_note(delivery_note),
        }
        delivery_note_data.update(
            edi._l10n_ec_get_info_tributaria(
                delivery_note,
                self.document_number,
                self._l10n_ec_get_document_code_sri(),
                xml_access_key,
            )
        )
        return delivery_note_data

    def _l10n_ec_get_details_delivery_note(self, delivery_note):
        res = []
        for line in delivery_note.delivery_line_ids:
            res.append(line.l10n_ec_get_delivery_note_edi_data())
        return res

    def action_process_edi_web_services(self):
        return ""

    def action_retry_edi_documents_error(self):
        return ""
