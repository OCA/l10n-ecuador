from contextlib import contextmanager

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.translate import _

STATES = {"draft": [("readonly", False)]}


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
        readonly=True,
        states=STATES,
        check_company=True,
        domain=[("l10n_latam_use_documents", "=", True), ("type", "=", "sale")],
    )
    transfer_date = fields.Date(
        required=True,
        readonly=True,
        states=STATES,
        default=lambda self: fields.Date.context_today(self),
        tracking=True,
    )
    delivery_date = fields.Date(
        required=True,
        readonly=True,
        states=STATES,
        default=lambda self: fields.Date.context_today(self),
        tracking=True,
    )
    motive = fields.Text(readonly=True, states=STATES, copy=False)
    l10n_ec_car_plate = fields.Char(
        "Car plate", size=8, required=False, readonly=True, states=STATES
    )
    stock_picking_ids = fields.Many2many(
        "stock.picking",
        string="Pickings related",
        readonly=True,
        states=STATES,
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
        readonly=True,
        states=STATES,
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
        readonly=True,
        states=STATES,
        index=True,
        tracking=True,
    )
    delivery_carrier_id = fields.Many2one(
        "res.partner",
        "Delivery Carrier",
        readonly=True,
        states=STATES,
        index=True,
        domain=[("l10n_ec_is_carrier", "=", True)],
    )
    delivery_note_type = fields.Selection(
        [
            ("sales", "Transfer by Sales"),
            ("internal", "Internal Transfer"),
        ],
        readonly=True,
        states=STATES,
        default="sales",
    )
    delivery_line_ids = fields.One2many(
        "l10n_ec.delivery.note.line",
        "delivery_note_id",
        "Delivery note detail",
        readonly=True,
        states=STATES,
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
        readonly=True,
        states=STATES,
        default=lambda self: self.env.company,
        required=True,
    )
    country_code = fields.Char(
        related="company_id.account_fiscal_country_id.code", readonly=True
    )
    rise = fields.Char("R.I.S.E", readonly=True, states=STATES, copy=False)
    dau = fields.Char("D.A.U.", readonly=True, states=STATES, copy=False)
    note = fields.Text(string="Notes", readonly=True, states=STATES, copy=False)
    origin = fields.Text(readonly=True, states=STATES, copy=False)
    invoice_id = fields.Many2one(
        "account.move", string="Invoice", readonly=True, states=STATES
    )

    edi_document_ids = fields.One2many(
        comodel_name="account.edi.document", inverse_name="l10n_ec_delivery_note_id"
    )
    edi_state = fields.Selection(
        selection=[
            ("to_send", "To Send"),
            ("sent", "Sent"),
            ("to_cancel", "To Cancel"),
            ("cancelled", "Cancelled"),
        ],
        string="Electronic invoicing",
        store=True,
        compute="_compute_edi_state",
        help="The aggregated state of all the EDIs with web-service of this move",
    )
    edi_error_count = fields.Integer(
        compute="_compute_edi_error_count",
        help="How many EDIs are in error for this move ?",
    )
    edi_blocking_level = fields.Selection(
        selection=[("info", "Info"), ("warning", "Warning"), ("error", "Error")],
        compute="_compute_edi_error_message",
    )
    edi_error_message = fields.Html(compute="_compute_edi_error_message")
    edi_web_services_to_process = fields.Text(
        compute="_compute_edi_web_services_to_process",
        help="Technical field to display the documents that will be processed by the CRON",
    )
    l10n_ec_authorization_date = fields.Datetime(
        compute="_compute_l10n_ec_edi_document_data",
        string="Access Key(EC)",
        store=True,
    )
    l10n_ec_xml_access_key = fields.Char(
        compute="_compute_l10n_ec_edi_document_data",
        string="Electronic Authorization Date",
        store=True,
    )
    l10n_ec_is_edi_doc = fields.Boolean(
        string="Is Ecuadorian Electronic Document", default=False, copy=False
    )

    l10n_latam_internal_type = fields.Many2one(
        "l10n_latam.document.type",
        string="Document Type",
        domain="[('code', '=', '06')]",
    )

    is_delivery_note_sent = fields.Boolean(default=False)

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

    @api.depends("edi_document_ids.state")
    def _compute_edi_state(self):
        for note in self:
            all_states = set(
                note.edi_document_ids.filtered(
                    lambda d: d.edi_format_id._needs_web_services()
                ).mapped("state")
            )
            if all_states == {"sent"}:
                note.edi_state = "sent"
            elif all_states == {"cancelled"}:
                note.edi_state = "cancelled"
            elif "to_send" in all_states:
                note.edi_state = "to_send"
            elif "to_cancel" in all_states:
                note.edi_state = "to_cancel"
            else:
                note.edi_state = False

    @api.depends("edi_document_ids.error")
    def _compute_edi_error_count(self):
        for note in self:
            note.edi_error_count = len(
                note.edi_document_ids.filtered(lambda d: d.error)
            )

    @api.depends(
        "edi_error_count", "edi_document_ids.error", "edi_document_ids.blocking_level"
    )
    def _compute_edi_error_message(self):
        for note in self:
            if note.edi_error_count == 0:
                note.edi_error_message = None
                note.edi_blocking_level = None
            elif note.edi_error_count == 1:
                error_doc = note.edi_document_ids.filtered(lambda d: d.error)
                note.edi_error_message = error_doc.error
                note.edi_blocking_level = error_doc.blocking_level
            else:
                error_levels = {doc.blocking_level for doc in note.edi_document_ids}
                if "error" in error_levels:
                    note.edi_error_message = str(note.edi_error_count) + _(
                        " Electronic delivery note error(s)"
                    )
                    note.edi_blocking_level = "error"
                elif "warning" in error_levels:
                    note.edi_error_message = str(note.edi_error_count) + _(
                        " Electronic delivery note warning(s)"
                    )
                    note.edi_blocking_level = "warning"
                else:
                    note.edi_error_message = str(note.edi_error_count) + _(
                        " Electronic delivery note info(s)"
                    )
                    note.edi_blocking_level = "info"

    @api.depends(
        "edi_document_ids",
        "edi_document_ids.state",
        "edi_document_ids.blocking_level",
        "edi_document_ids.edi_format_id",
        "edi_document_ids.edi_format_id.name",
    )
    def _compute_edi_web_services_to_process(self):
        for note in self:
            to_process = note.edi_document_ids.filtered(
                lambda d: d.state in ["to_send", "to_cancel"]
                and d.blocking_level != "error"
            )
            format_web_services = to_process.edi_format_id.filtered(
                lambda f: f._needs_web_services()
            )
            note.edi_web_services_to_process = ", ".join(
                f.name for f in format_web_services
            )

    @api.depends(
        "edi_document_ids.l10n_ec_authorization_date",
        "edi_document_ids.l10n_ec_xml_access_key",
    )
    def _compute_l10n_ec_edi_document_data(self):
        for note in self:
            edi_doc = note.edi_document_ids.filtered(
                lambda d: d.edi_format_id.code == "l10n_ec_format_sri"
            )
            note.l10n_ec_authorization_date = edi_doc.l10n_ec_authorization_date
            note.l10n_ec_xml_access_key = edi_doc.l10n_ec_xml_access_key

    # @api.onchange("transfer_date", "delivery_date")
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
            if (
                delivery.journal_id.l10n_ec_emission_type == "electronic"
                and delivery.transfer_date
                and delivery.transfer_date > date_current
            ):
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
                "Document number of Delivery Note must be Unique by company, please check"
            ),
        )
    ]

    @api.model
    def default_get(self, fields_list):
        defaults = super(DeliveryNote, self).default_get(fields_list)
        document_type = self.env["l10n_latam.document.type"].search(
            [("code", "=", "06")], limit=1
        )
        defaults["l10n_latam_internal_type"] = document_type.id

        return defaults

    def unlink(self):
        for delivery_note in self:
            if delivery_note.state != "draft":
                raise UserError(_("Cant'n unlink Delivery Note, Try cancel!"))
        return super(DeliveryNote, self).unlink()

    def action_confirm(self):
        for delivery_note in self:
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

    def action_process_edi_web_services(self, with_commit=True):
        docs = self.edi_document_ids.filtered(
            lambda d: d.state in ("to_send", "to_cancel")
            and d.blocking_level != "error"
        )
        docs._process_documents_web_services(with_commit=with_commit)

    def action_retry_edi_documents_error(self):
        self.edi_document_ids.write({"error": False, "blocking_level": False})
        self.action_process_edi_web_services()

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
        # Set the electronic document to be posted and post immediately for synchronous formats.
        edi_document_vals_list = []
        for note in self:
            for edi_format in note.journal_id.edi_format_ids:
                is_edi_needed = edi_format.l10n_ec_is_required_for_delivery_note(note)
                if is_edi_needed:
                    errors = edi_format._l10n_ec_check_delivery_note_configuration(note)
                    if errors:
                        raise UserError(
                            _("Invalid delivery note configuration:\n\n%s")
                            % "\n".join(errors)
                        )
                    existing_edi_document = note.edi_document_ids.filtered(
                        lambda x: x.edi_format_id == edi_format
                    )
                    if existing_edi_document:
                        existing_edi_document.write(
                            {
                                "state": "to_send",
                                "attachment_id": False,
                            }
                        )
                    else:
                        edi_document_vals_list.append(
                            {
                                "edi_format_id": edi_format.id,
                                "l10n_ec_delivery_note_id": note.id,
                                "state": "to_send",
                            }
                        )
        self.env["account.edi.document"].create(edi_document_vals_list)
        self.edi_document_ids._process_documents_no_web_services()
        self.env.ref("account_edi.ir_cron_edi_network")._trigger()
        return self

    @contextmanager
    def _send_only_when_ready(self):
        delivery_note_not_ready = self.filtered(lambda x: not x._is_ready_to_be_sent())
        try:
            yield
        finally:
            delivery_note_not_ready.filtered(lambda x: x._is_ready_to_be_sent())

    def _is_ready_to_be_sent(self):
        # Prevent a mail to be sent to the customer if the EDI document is not sent.
        edi_documents_to_send = self.edi_document_ids.filtered(
            lambda x: x.state == "to_send"
        )
        return not bool(edi_documents_to_send)

    def _get_edi_document(self, edi_format):
        return self.edi_document_ids.filtered(lambda d: d.edi_format_id == edi_format)

    # Métodos del portal
    def _compute_access_url(self):
        res = super(DeliveryNote, self)._compute_access_url()
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
            "default_res_id": self.id,
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
