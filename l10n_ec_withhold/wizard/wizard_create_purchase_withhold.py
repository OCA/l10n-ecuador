from odoo import _, api, fields, models
from odoo.exceptions import UserError

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
                    "account_id": self.partner_id.property_account_payable_id.id,
                    "name": "RET " + str(self.document_number),
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
        # replace function to compute base_amount considering l10n_ec_tax_support
        for line in self:
            if not line.l10n_ec_tax_support:
                line.base_amount = 0.0
                continue
            base_amount = 0.0
            for invoice_line in line.invoice_id.invoice_line_ids:
                l10n_ec_tax_support = (
                    invoice_line.l10n_ec_tax_support
                    or line.invoice_id.l10n_ec_tax_support
                )
                if l10n_ec_tax_support == line.l10n_ec_tax_support:
                    if (
                        line.tax_group_withhold_id.l10n_ec_type
                        == "withhold_income_purchase"
                    ):
                        base_amount += abs(invoice_line.price_subtotal)
                    elif line.tax_group_withhold_id.l10n_ec_type == "withhold_vat":
                        base_amount += abs(
                            invoice_line.price_total - invoice_line.price_subtotal
                        )
            line.base_amount = base_amount

    def _prepare_amount_vals(self, wizard, tax_data):
        vals = super()._prepare_amount_vals(wizard, tax_data)
        vals["l10n_ec_tax_support"] = self.l10n_ec_tax_support
        return vals

    def _prepare_basis_vals(self, wizard, tax_data):
        vals = super()._prepare_basis_vals(wizard, tax_data)
        vals["l10n_ec_tax_support"] = self.l10n_ec_tax_support
        return vals
