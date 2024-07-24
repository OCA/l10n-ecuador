from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_is_zero

from ..models.data import TAX_SUPPORT


class WizardCreatePurchaseWithhold(models.TransientModel):
    _inherit = "l10n_ec.wizard.abstract.withhold"
    _name = "l10n_ec.wizard.create.purchase.withhold"
    _description = "Wizard Purchase withhold"

    withhold_line_ids = fields.One2many(
        comodel_name="l10n_ec.wizard.create.purchase.withhold.line",
        inverse_name="withhold_id",
        string="Lines",
        required=True,
    )
    withhold_totals = fields.Float(compute="_compute_total_withhold", store=True)

    @api.depends("withhold_line_ids.withhold_amount")
    def _compute_total_withhold(self):
        for record in self:
            record.withhold_totals = sum(
                record.withhold_line_ids.mapped("withhold_amount")
            )

    def _prepare_withholding_vals(self):
        withholding_vals = super()._prepare_withholding_vals()
        withholding_vals["l10n_ec_withholding_type"] = "purchase"
        return withholding_vals

    def button_validate(self):
        """
        Create a purchase Withholding and try reconcile with invoice
        """
        self.ensure_one()
        if not self.withhold_line_ids:
            raise UserError(_("Please add some withholding lines before continue"))
        tax_support_string = dict(
            self.withhold_line_ids._fields["l10n_ec_tax_support"].selection
        )
        for line in self.withhold_line_ids:
            has_lines_with_tax_and_tax_support = False
            for invoice_line in line.invoice_id.invoice_line_ids:
                l10n_ec_tax_support = (
                    invoice_line.l10n_ec_tax_support
                    or line.invoice_id.l10n_ec_tax_support
                )
                if (
                    l10n_ec_tax_support == line.l10n_ec_tax_support
                    and invoice_line.tax_ids
                ):
                    has_lines_with_tax_and_tax_support = True
            if not has_lines_with_tax_and_tax_support:
                raise UserError(
                    _(
                        "The base amount for withholding is zero.\n"
                        "Review withholding lines with Tax Support: %s.\n"
                        "Please ensure the following:\n"
                        " - The tax support of the invoice lines"
                        "(or Tax support on the invoice) "
                        "is equal to Tax support of the withholding line.\n"
                        " - The invoice lines have taxes "
                        "correctly configured(VAT or Profit).",
                        tax_support_string.get(line.l10n_ec_tax_support),
                    )
                )
        withholding_vals = self._prepare_withholding_vals()
        total_by_invoice = {}
        lines = []
        for line in self.withhold_line_ids:
            taxes_vals = line._get_withholding_line_vals(self)
            total_counter = abs(line.withhold_amount)
            total_by_invoice.setdefault(line.invoice_id, 0.0)
            total_by_invoice[line.invoice_id] += total_counter
            for tax_vals in taxes_vals:
                lines.append((0, 0, tax_vals))
        for invoice, total_counter in total_by_invoice.items():
            move_name = _(
                "RET: %(document_number)s Invoice: %(invoice_number)s",
                document_number=self.document_number,
                invoice_number=invoice.l10n_latam_document_number,
            )
            lines.append(
                (
                    0,
                    0,
                    {
                        "partner_id": self.partner_id.id,
                        "account_id": self.partner_id.property_account_payable_id.id,
                        "l10n_ec_invoice_withhold_id": invoice.id,
                        "name": move_name,
                        "debit": total_counter,
                        "credit": 0.0,
                    },
                )
            )

        withholding_vals.update({"line_ids": lines})
        new_withholding = self.env["account.move"].create(withholding_vals)
        new_withholding._post()
        invoices = self.withhold_line_ids.invoice_id
        invoices.write({"l10n_ec_withhold_ids": [(4, new_withholding.id)]})
        self._try_reconcile_withholding_moves(
            new_withholding, invoices, "liability_payable"
        )
        withholding_lines = new_withholding.line_ids.filtered(lambda line: line.tax_ids)
        withholding_lines.write({"l10n_ec_withhold_id": new_withholding.id})
        return True


class WizardPurchaseWithholdLine(models.TransientModel):
    _inherit = "l10n_ec.wizard.abstract.withhold.line"
    _name = "l10n_ec.wizard.create.purchase.withhold.line"
    _description = "Wizard Purchase withhold line"

    withhold_id = fields.Many2one(
        comodel_name="l10n_ec.wizard.create.purchase.withhold",
        string="Withhold",
        ondelete="cascade",
    )
    l10n_ec_tax_support = fields.Selection(
        TAX_SUPPORT,
        string="Tax Support",
        copy=False,
    )

    @api.onchange("invoice_id", "tax_group_withhold_id", "l10n_ec_tax_support")
    def _onchange_withholding_base(self):
        res = {
            "value": {},
            "warning": {},
        }
        # replace function to compute base_amount considering l10n_ec_tax_support
        if not self.l10n_ec_tax_support or not self.tax_group_withhold_id:
            res["value"]["base_amount"] = 0.0
            return res
        currency_prec = self.invoice_id.company_id.currency_id.rounding
        base_amount = 0.0
        for invoice_line in self.invoice_id.invoice_line_ids:
            l10n_ec_tax_support = (
                invoice_line.l10n_ec_tax_support or self.invoice_id.l10n_ec_tax_support
            )
            if l10n_ec_tax_support == self.l10n_ec_tax_support and invoice_line.tax_ids:
                if (
                    self.tax_group_withhold_id.l10n_ec_type
                    == "withhold_income_purchase"
                ):
                    base_amount += abs(invoice_line.price_subtotal)
                elif self.tax_group_withhold_id.l10n_ec_type == "withhold_vat_purchase":
                    base_amount += abs(
                        invoice_line.price_total - invoice_line.price_subtotal
                    )
        if float_is_zero(base_amount, precision_rounding=currency_prec):
            res["value"]["base_amount"] = 0.0
            res["warning"] = {
                "title": _("User Information"),
                "message": _(
                    "The base amount for withholding is zero. "
                    "Please ensure the following:\n"
                    " - The tax support of the invoice lines"
                    "(or Tax support on the invoice) "
                    "is equal to Tax support of the withholding line.\n"
                    " - The invoice lines have taxes "
                    "correctly configured(VAT or Profit)."
                ),
            }
            return res
        self.base_amount = base_amount

    def _prepare_basis_vals(self, wizard, tax_data):
        vals = super()._prepare_basis_vals(wizard, tax_data)
        vals["l10n_ec_tax_support"] = self.l10n_ec_tax_support
        return vals
