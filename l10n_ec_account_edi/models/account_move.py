import logging
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare

from odoo.addons.l10n_ec.models.res_partner import (
    PartnerIdTypeEc,
    verify_final_consumer,
)

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

    @api.depends("company_id", "invoice_filter_type_domain")
    def _compute_suitable_journal_ids(self):
        super()._compute_suitable_journal_ids()
        Journal = self.env["account.journal"]
        is_purchase_liquidation = (
            self.env.context.get("internal_type", "") == "purchase_liquidation"
        )
        for move in self:
            company = move.company_id or self.env.company
            if company.account_fiscal_country_id.code != "EC":
                continue
            journal_type = move.invoice_filter_type_domain or "general"
            move.suitable_journal_ids = Journal.search(
                [
                    *Journal._check_company_domain(company),
                    ("type", "=", journal_type),
                    ("l10n_ec_is_purchase_liquidation", "=", is_purchase_liquidation),
                ]
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

    def _search_default_journal(self):
        is_purchase_liquidation = (
            self.env.context.get("internal_type", "") == "purchase_liquidation"
        )
        company = self.company_id or self.env.company
        if (
            not is_purchase_liquidation
            or company.account_fiscal_country_id.code != "EC"
        ):
            return super()._search_default_journal()
        journal_types = self._get_valid_journal_types()
        domain = [
            *self.env["account.journal"]._check_company_domain(company),
            ("type", "in", journal_types),
            ("l10n_ec_is_purchase_liquidation", "=", is_purchase_liquidation),
        ]

        journal = None
        # the currency is not a hard dependence, it triggers via manual add_to_compute
        # avoid computing the currency before all it's dependences are set (like the journal...)
        if self.env.cache.contains(self, self._fields["currency_id"]):
            currency_id = self.currency_id.id or self._context.get(
                "default_currency_id"
            )
            if currency_id and currency_id != company.currency_id.id:
                currency_domain = domain + [("currency_id", "=", currency_id)]
                journal = self.env["account.journal"].search(currency_domain, limit=1)

        if not journal:
            journal = self.env["account.journal"].search(domain, limit=1)

        if not journal:
            error_msg = _(
                "No journal could be found in company %(company_name)s for any of those types: %(journal_types)s",
                company_name=company.display_name,
                journal_types=", ".join(journal_types),
            )
            raise UserError(error_msg)

        return journal

    def action_post(self):
        for move in self:
            if move.company_id.account_fiscal_country_id.code == "EC":
                move._l10n_ec_validate_quantity_move_line()
        return super().action_post()

    def _is_l10n_ec_is_purchase_liquidation(self):
        self.ensure_one()
        return (
            self.country_code == "EC"
            and self.l10n_latam_internal_type == "purchase_liquidation"
        )

    def _l10n_ec_get_payment_data(self):
        payment_data = []
        credit_days = self.l10n_ec_credit_days
        foreign_currency = (
            self.currency_id
            if self.currency_id != self.company_id.currency_id
            else False
        )
        pay_term_line_ids = self.line_ids.filtered(
            lambda line: line.account_id.account_type
            in ("asset_receivable", "liability_payable")
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
            l10n_ec_sri_payment = (
                self.l10n_ec_sri_payment_id or self.journal_id.l10n_ec_sri_payment_id
            )
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

        def filter_withholding_taxes(base_line, tax_values):
            withhold_group_ids = (
                self.env["account.tax.group"]
                .search(
                    [("l10n_ec_type", "in", ("withhold_vat", "withhold_income_tax"))]
                )
                .ids
            )
            return (
                tax_values["tax_repartition_line"].tax_id.tax_group_id.id
                not in withhold_group_ids
            )

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
                    lambda x: x.display_type == "product"
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
        # support to purchase liquidation and debit note
        is_purchase_liquidation = (
            self.env.context.get("internal_type") == "purchase_liquidation"
        )
        is_debit_note = self.env.context.get("internal_type") == "debit_note"
        internal_type = ""
        if is_purchase_liquidation:
            internal_type = "purchase_liquidation"
        elif is_debit_note:
            internal_type = "debit_note"
        if (
            self.l10n_latam_use_documents
            and self.company_id.account_fiscal_country_id.code == "EC"
            and internal_type
        ):
            return [
                ("country_id.code", "=", "EC"),
                ("internal_type", "=", internal_type),
            ]
        return super()._get_l10n_latam_documents_domain()

    def l10n_ec_get_identification_type(self):
        # codigos son tomados de la ficha tecnica del SRI, tabla 6
        partner = self.commercial_partner_id
        partner_vat_type = partner._l10n_ec_get_identification_type()
        if verify_final_consumer(partner.vat):
            return PartnerIdTypeEc.FINAL_CONSUMER.value
        elif partner_vat_type == "foreign":
            return PartnerIdTypeEc.FOREIGN.value
        else:
            # para liquidacion de compras tomar como si fuera de ventas los codigos
            # pasar out_ ya que solo evalua con que inicias el codigo
            move_type = self.move_type
            if self._is_l10n_ec_is_purchase_liquidation():
                move_type = "out_"
            return PartnerIdTypeEc.get_ats_code_for_partner(partner, move_type).value

    def _is_manual_document_number(self):
        is_purchase = super()._is_manual_document_number()
        if is_purchase and self._is_l10n_ec_is_purchase_liquidation():
            return False
        return is_purchase

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
                    and doc.edi_format_id._get_move_applicability(move).get("cancel")
                ):
                    move.show_reset_to_draft_button = False
                    break

        return response

    def action_send_and_print(self):
        if any(x._is_l10n_ec_is_purchase_liquidation() for x in self):
            template = self.env.ref(self._get_mail_template(), raise_if_not_found=False)
            return {
                "name": _("Send"),
                "type": "ir.actions.act_window",
                "view_type": "form",
                "view_mode": "form",
                "res_model": "account.move.send",
                "target": "new",
                "context": {
                    "active_ids": self.ids,
                    "default_mail_template_id": template.id,
                },
            }
        return super().action_send_and_print()

    def l10n_ec_send_email(self):
        WizardInvoiceSent = self.env["account.move.send"]
        self.ensure_one()
        res = self.with_context(discard_logo_check=True).action_invoice_sent()
        context = res["context"]
        send_mail = WizardInvoiceSent.with_context(**context).create({})
        # enviar factura automaticamente por correo
        send_mail.action_send_and_print()

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
