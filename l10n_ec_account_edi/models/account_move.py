import logging
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = "account.move"

    l10n_ec_sri_payment_id = fields.Many2one(
        default=lambda self: self.env.ref("l10n_ec.P1")
    )

    l10n_ec_credit_days = fields.Integer(
        string="Credit days", compute="_compute_l10n_ec_credit_days", store=True
    )
    l10n_latam_internal_type = fields.Selection(
        related="l10n_latam_document_type_id.internal_type",
        string="L10n Latam Internal Type",
        store=True,
    )
    l10n_ec_electronic_authorization = fields.Char(
        string="Electronic Authorization", size=49, copy=False, index=True
    )
    l10n_ec_journal_type = fields.Selection(
        related="journal_id.type",
        string="Journal Type",
        store=True,
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
    l10n_ec_legacy_document_date = fields.Date(string="External Document Date")
    l10n_ec_legacy_document_number = fields.Char(string="External Document Number")
    l10n_ec_legacy_document_authorization = fields.Char(
        string="External Authorization Number", size=49
    )
    l10n_ec_reason = fields.Char(string="Refund Reason", size=300)

    l10n_ec_additional_information_move_ids = fields.One2many(
        "l10n.ec.additional.information", "move_id", string="Additional Information"
    )

    @api.depends("invoice_date", "invoice_date_due")
    def _compute_l10n_ec_credit_days(self):
        now = fields.Date.context_today(self)
        for invoice in self:
            date_invoice = invoice.invoice_date or now
            date_due = invoice.invoice_date_due or date_invoice
            invoice.l10n_ec_credit_days = (date_due - date_invoice).days

    @api.depends(
        "edi_document_ids.l10n_ec_authorization_date",
        "edi_document_ids.l10n_ec_xml_access_key",
    )
    def _compute_l10n_ec_edi_document_data(self):
        for note in self:
            edi_doc = note.edi_document_ids.filtered(
                lambda d: d.edi_format_id.code == "l10n_ec_format_sri"
            )
            note.l10n_ec_authorization_date = (
                edi_doc.l10n_ec_authorization_date or False
            )
            note.l10n_ec_xml_access_key = edi_doc.l10n_ec_xml_access_key or ""

    @api.constrains(
        "l10n_ec_electronic_authorization",
    )
    def _check_l10n_ec_electronic_authorization_number(self):
        cadena = r"(\d{10})"
        for rec in self:
            if rec.l10n_ec_electronic_authorization and not re.match(
                cadena, rec.l10n_ec_electronic_authorization
            ):
                raise UserError(
                    _("Invalid provider authorization number, must be numeric only")
                )

    def action_post(self):
        for move in self:
            if move.company_id.country_id.code == "EC":
                move._l10n_ec_validate_quantity_move_line()
        return super(AccountMove, self).action_post()

    def _l10n_ec_get_payment_data(self):
        payment_data = []
        credit_days = self.l10n_ec_credit_days
        foreign_currency = (
            self.currency_id
            if self.currency_id != self.company_id.currency_id
            else False
        )
        pay_term_line_ids = self.line_ids.filtered(
            lambda line: line.account_id.user_type_id.type in ("receivable", "payable")
        )
        partials = pay_term_line_ids.mapped(
            "matched_debit_ids"
        ) + pay_term_line_ids.mapped("matched_credit_ids")
        for partial in partials:
            counterpart_lines = partial.debit_move_id + partial.credit_move_id
            counterpart_line = counterpart_lines.filtered(
                lambda line: line not in self.line_ids
            )
            if not counterpart_line.payment_id.journal_id.l10n_ec_sri_payment_id:
                continue
            if foreign_currency and counterpart_line.currency_id == foreign_currency:
                amount = counterpart_line.amount_currency
            else:
                amount = partial.company_currency_id._convert(
                    partial.amount,
                    self.currency_id,
                    self.company_id,
                    self.date,
                )
            payment_vals = {
                "name": counterpart_line.payment_id.journal_id.l10n_ec_sri_payment_id.name,
                "formaPago": counterpart_line.payment_id.journal_id.l10n_ec_sri_payment_id.code,
                "total": self.edi_document_ids._l10n_ec_number_format(amount),
            }
            if self.invoice_payment_term_id and credit_days:
                payment_vals.update(
                    {
                        "plazo": credit_days,
                        "unidadTiempo": "dias",
                    }
                )
            payment_data.append(payment_vals)
        if not payment_data:
            l10n_ec_sri_payment = self.journal_id.l10n_ec_sri_payment_id
            payment_vals = {
                "name": l10n_ec_sri_payment.name,
                "formaPago": l10n_ec_sri_payment.code,
                "total": self.edi_document_ids._l10n_ec_number_format(
                    self.amount_total
                ),
            }
            if self.invoice_payment_term_id and credit_days:
                payment_vals.update(
                    {
                        "plazo": credit_days,
                        "unidadTiempo": "dias",
                    }
                )
            payment_data.append(payment_vals)
        return payment_data

    def _l10n_ec_get_taxes_grouped_by_tax_group(self, exclude_withholding=True):
        self.ensure_one()

        def filter_withholding_taxes(tax_values):
            withhold_group_ids = (
                self.env["account.tax.group"]
                .search(
                    [("l10n_ec_type", "in", ("withhold_vat", "withhold_income_tax"))]
                )
                .ids
            )
            return tax_values["tax_id"].tax_group_id.id not in withhold_group_ids

        taxes_data = self._prepare_edi_tax_details(
            filter_to_apply=exclude_withholding and filter_withholding_taxes or None,
        )
        return taxes_data

    def _get_name_invoice_report(self):
        self.ensure_one()
        if (
            self.l10n_latam_use_documents
            and self.company_id.account_fiscal_country_id.code == "EC"
            and self.edi_document_ids.filtered(
                lambda x: x.edi_format_id.code == "l10n_ec_format_sri"
            )
        ):
            return "l10n_ec_account_edi.report_invoice_document"
        return super()._get_name_invoice_report()

    def _l10n_ec_get_document_date(self):
        return self.invoice_date

    def _l10n_ec_get_document_name(self):
        return self.display_name

    def _l10n_ec_get_document_code_sri(self):
        # factura de venta es codigo 18, pero aca debe pasarse codigo 01
        # los demas documentos tomar del tipo de documento(l10n_latam_document_type_id)
        document_code_sri = self.l10n_latam_document_type_id.code
        if self.l10n_latam_internal_type == "invoice":
            document_code_sri = "01"
        return document_code_sri

    def _l10n_ec_get_edi_document(self, withhold=False):
        """Retorna edi_document, donde edi_format contiene el código proporcionado,
        todos los documentos usan el mismo edi_format a excepción de retenciones,
        similar al método _get_edi_document; pero la búsqueda es por id de edi_format"""
        code = "l10n_ec_format_sri"
        if withhold:
            code = "l10n_ec_withhold_format_sri"
        return self.edi_document_ids.filtered(lambda d: d.edi_format_id.code == code)

    def _l10n_ec_validate_quantity_move_line(self):
        error_list, product_not_quantity = [], []
        for move in self:
            if move.move_type in (
                "in_invoice",
                "out_invoice",
                "in_refund",
                "out_refund",
            ):
                for line in move.invoice_line_ids.filtered(
                    lambda x: not x.display_type
                ):
                    if float_compare(line.quantity, 0.0, precision_digits=2) <= 0:
                        product_not_quantity.append(
                            "  - %s" % line.product_id.display_name
                        )
                if product_not_quantity:
                    error_list.append(
                        _(
                            "You cannot validate an invoice with zero quantity. "
                            "Please review the following items:\n%s"
                        )
                        % "\n".join(product_not_quantity)
                    )
                if float_compare(move.amount_total, 0.0, precision_digits=2) <= 0:
                    error_list.append(
                        _("You cannot validate an invoice with zero value.")
                    )
                if error_list:
                    raise UserError("\n".join(error_list))

    def _get_l10n_latam_documents_domain(self):
        self.ensure_one()
        if (
            self.journal_id.company_id.account_fiscal_country_id
            != self.env.ref("base.ec")
            or not self.journal_id.l10n_latam_use_documents
        ):
            return super()._get_l10n_latam_documents_domain()
        domain = [
            ("country_id.code", "=", "EC"),
            (
                "internal_type",
                "in",
                [
                    "invoice",
                    "debit_note",
                    "credit_note",
                    "invoice_in",
                    "purchase_liquidation",
                ],
            ),
        ]
        internal_type = self._get_l10n_ec_internal_type()
        allowed_documents = self._get_l10n_ec_documents_allowed(
            self._get_l10n_ec_identification_type()
        )
        if internal_type and allowed_documents:
            domain.append(
                (
                    "id",
                    "in",
                    allowed_documents.filtered(
                        lambda x: x.internal_type == internal_type
                    ).ids,
                )
            )
        return domain

    def l10n_ec_get_identification_type(self):
        # codigos son tomados de la ficha tecnica del SRI, tabla 6
        identification_type = self._get_l10n_ec_identification_type()
        if identification_type == "01":  # Ruc
            return "04"
        elif identification_type == "02":  # Dni
            return "05"
        elif identification_type == "03":  # Passapot
            if self.partner_id.commercial_partner_id.country_id.code != "EC":
                return "08"
            return "06"
        elif identification_type in ("21", "20", "19"):
            return "08"
        return identification_type

    def _is_manual_document_number(self):
        is_purchase = super()._is_manual_document_number()
        if is_purchase:
            if self.l10n_latam_document_type_id.internal_type == "purchase_liquidation":
                return False
        return is_purchase

    def _reverse_move_vals(self, default_values, cancel=True):
        move_vals = super()._reverse_move_vals(default_values, cancel)
        move_vals.update(
            l10n_ec_legacy_document_number=self.l10n_latam_document_number,
            l10n_ec_legacy_document_date=self.invoice_date,
            l10n_ec_legacy_document_authorization=self.l10n_ec_xml_access_key,
        )
        return move_vals

    def _compute_show_reset_to_draft_button(self):
        """
        Hide button reset to draft when receipt is cancelled
        """
        response = super()._compute_show_reset_to_draft_button()

        for move in self:
            for doc in move.edi_document_ids:
                if (
                    doc.edi_format_id._needs_web_services()
                    and doc.state == "cancelled"
                    and doc.l10n_ec_authorization_date
                    and move.is_invoice(include_receipts=True)
                    and doc.edi_format_id._is_required_for_invoice(move)
                ):
                    move.show_reset_to_draft_button = False
                    break

        return response

    def l10n_ec_send_email(self):
        WizardInvoiceSent = self.env["account.invoice.send"]
        self.ensure_one()
        res = self.with_context(discard_logo_check=True).action_invoice_sent()
        context = res["context"]
        send_mail = WizardInvoiceSent.with_context(**context).create({})
        # enviar factura automaticamente por correo
        # simular onchange y accion
        send_mail.onchange_template_id()
        send_mail.send_and_print_action()

    def button_cancel_posted_moves(self):
        """
        Restrict the cancel process when receipt is authorized or
        connection to the SRI is not possible
        """
        for receipt in self:
            company = receipt.env.user.company_id
            client_ws = receipt.edi_document_ids.edi_format_id

            authorization_client = client_ws._l10n_ec_get_edi_ws_client(
                company.l10n_ec_type_environment, "authorization"
            )

            response = receipt.edi_document_ids._l10n_ec_edi_send_xml_auth(
                authorization_client
            )

            if response is False:
                raise ValidationError(
                    _(
                        "The connection to the SRI service is not possible. Please check later."
                    )
                )

            is_authorized = receipt.edi_document_ids._l10n_ec_edi_process_response_auth(
                response
            )[0]

            if is_authorized:
                raise ValidationError(
                    _("The receipt is authorized. It cannot be cancelled.")
                )

        return super().button_cancel_posted_moves()
