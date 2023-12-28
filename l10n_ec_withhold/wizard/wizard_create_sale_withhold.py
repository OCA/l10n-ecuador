import datetime
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class WizardCreateSaleWithhold(models.TransientModel):
    _inherit = "l10n_ec.wizard.abstract.withhold"
    _name = "l10n_ec.wizard.create.sale.withhold"
    _description = "Wizard Sale withhold"

    withhold_line_ids = fields.One2many(
        comodel_name="l10n_ec.wizard.create.sale.withhold.line",
        inverse_name="withhold_id",
        string="Lines",
        required=True,
    )
    withhold_totals = fields.Float(compute="_compute_total_withhold", store=True)
    invoice_ids = fields.Many2many(comodel_name="account.move", string="Invoice")

    @api.model
    def default_get(self, fields):
        defaults = super().default_get(fields)
        invoices = (
            self.env["account.move"]
            .browse(self.env.context.get("active_ids"))
            .filtered("l10n_ec_withhold_active")
        )
        if len(invoices.partner_id) > 1:
            raise UserError(_("Please only select invoice of a same customer"))
        if any(invoice.payment_state == "paid" for invoice in invoices):
            raise UserError(
                _("The selected invoice is paid or one of selected invoice is paid")
            )
        defaults["invoice_ids"] = [(6, 0, invoices.ids)]
        defaults["partner_id"] = invoices.partner_id.id
        if len(invoices) == 1:
            defaults["invoice_id"] = invoices.id
            defaults["issue_date"] = invoices.invoice_date
        # Default Journal
        journal = self.env["account.journal"].search([('type', '=', 'general'), ('l10n_ec_withholding_type', '=', 'sale')], limit=1)
        if journal:
            defaults["journal_id"] = journal.id
        
        return defaults

    @api.depends("withhold_line_ids.withhold_amount")
    def _compute_total_withhold(self):
        for record in self:
            record.withhold_totals = sum(
                record.withhold_line_ids.mapped("withhold_amount")
            )

    def _prepare_withholding_vals(self):
        withholding_vals = super()._prepare_withholding_vals()
        withholding_vals["l10n_ec_withholding_type"] = "sale"
        return withholding_vals

    @api.onchange("electronic_authorization")
    def onchange_authorization(self):
        if self.electronic_authorization:
            if len(self.electronic_authorization) == 49:
                if self.electronic_authorization[8:10] == "07":
                    self.issue_date = self.extract_date_from_authorization()
                    self.document_number = (
                        self.extract_document_number_from_authorization()
                    )
                else:
                    raise UserError(
                        _("Authorization number not correspond to a withhold")
                    )

            self.validate_authorization()

    @api.onchange("document_number")
    def onchange_document_number(self):
        if self.document_number:
            self.document_number = self._format_document_number(self.document_number)

    def _format_document_number(self, document_number):
        document_number = re.sub(r"\s+", "", document_number)  # remove any whitespace
        num_match = re.match(r"(\d{1,3})-(\d{1,3})-(\d{1,9})", document_number)
        if num_match:
            # Fill each number group with zeroes (3, 3 and 9 respectively)
            document_number = "-".join(
                [n.zfill(3 if i < 2 else 9) for i, n in enumerate(num_match.groups())]
            )
        else:
            raise UserError(
                _("Ecuadorian Document %s must be like 001-001-123456789")
                % (document_number)
            )

        return document_number

    def validate_authorization(self):
        authorization_len = len(self.electronic_authorization)
        if authorization_len not in [10, 49]:
            raise UserError(
                _("Authorization is not valid. Should be length equal to 10 or 49")
            )

    def validate_repeated_invoice(self):
        for line in self.withhold_line_ids:
            result = self.env["account.move.line"].search(
                [
                    ("l10n_ec_invoice_withhold_id", "=", line.invoice_id.id),
                    ("move_id.l10n_ec_withholding_type", "=", "sale"),
                    ("move_id.l10n_latam_internal_type", "=", "withhold"),
                    ("move_id.state", "=", "posted"),
                ],
                limit=1,
            )
            if len(result) > 0:
                raise UserError(
                    _(
                        f"Invoice {line.invoice_id.name} already exist in withhold "
                        f"{result.move_id.name}"
                    )
                )

    def validate_repeated_withhold(self):
        withhold_count = self.env["account.move"].search_count(
            [
                ("partner_id", "=", self.partner_id.id),
                ("name", "=", f"RET {self.document_number}"),
                ("l10n_ec_withholding_type", "=", "sale"),
                ("l10n_latam_internal_type", "=", "withhold"),
                ("state", "=", "posted"),
            ]
        )
        if withhold_count > 0:
            raise UserError(_(f"Withhold {self.document_number} already exist"))

    def validate_selected_invoices(self):
        if len(self.withhold_line_ids.invoice_id) != len(self.invoice_ids):
            raise UserError(_("Withhold not content selected invoices"))

    def validate(self):
        if not self.withhold_line_ids:
            raise UserError(_("Please add some withholding lines before continue"))
        for invoice in self.invoice_ids:
            if self.issue_date < invoice.invoice_date:
                raise UserError(
                    _(
                        f"Withhold date: {self.issue_date} "
                        f"should be equal or major that invoice date: {invoice.invoice_date}"
                    )
                )
        self.validate_selected_invoices()
        self.validate_authorization()
        self.validate_repeated_withhold()
        self.validate_repeated_invoice()

    def extract_date_from_authorization(self):
        return datetime.datetime.strptime(
            self.electronic_authorization[0:8], "%d%m%Y"
        ).date()

    def extract_document_number_from_authorization(self):
        series_number = self.electronic_authorization[24:39]
        return f"{series_number[0:3]}-{series_number[3:6]}-{series_number[6:15]}"

    def button_validate(self):
        """
        Create a Sale Withholding and try reconcile with invoice
        """
        self.ensure_one()
        self.validate()

        withholding_vals = self._prepare_withholding_vals()
        total_counter = 0
        lines = []
        for line in self.withhold_line_ids:
            taxes_vals = line._get_withholding_line_vals(self)
            for tax_vals in taxes_vals:                
                lines.append((0, 0, tax_vals))
                if tax_vals.get("tax_tag_ids"):                    
                    total_counter += abs(tax_vals.get("price_unit"))

        lines.append(
            (
                0,
                0,
                {
                    "partner_id": self.partner_id.id,
                    "account_id": self.partner_id.property_account_receivable_id.id,
                    "name": "RET " + str(self.document_number),
                    "debit": 0.00,
                    "credit": total_counter,
                },
            )
        )

        withholding_vals.update({"line_ids": lines})
        new_withholding = self.env["account.move"].create(withholding_vals)
        new_withholding.action_post()
        invoices = self.withhold_line_ids.invoice_id
        invoices.write({"l10n_ec_withhold_ids": [(4, new_withholding.id)]})
        self._try_reconcile_withholding_moves(
            new_withholding, invoices, "asset_receivable"
        )
        return True


class WizardCreateSaleWithholdLine(models.TransientModel):
    _inherit = "l10n_ec.wizard.abstract.withhold.line"
    _name = "l10n_ec.wizard.create.sale.withhold.line"
    _description = "Wizard Sale withhold line"

    withhold_id = fields.Many2one(
        comodel_name="l10n_ec.wizard.create.sale.withhold",
        string="Withhold",
        ondelete="cascade",
    )
