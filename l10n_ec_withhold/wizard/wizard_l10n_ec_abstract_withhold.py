from odoo import _, api, fields, models


class WizardAbstractWithhold(models.AbstractModel):
    _name = "l10n_ec.wizard.abstract.withhold"
    _description = "Abstract Withhold Wizard"

    partner_id = fields.Many2one(
        "res.partner",
        string="Partner",
    )
    issue_date = fields.Date(
        string="Date",
        required=True,
    )
    journal_id = fields.Many2one(comodel_name="account.journal", string="Journal")
    document_number = fields.Char(
        required=True,
        size=17,
    )
    electronic_authorization = fields.Char(
        size=49,
        required=False,
    )
    invoice_id = fields.Many2one(
        comodel_name="account.move",
        string="Related Document",
        readonly=True,
    )

    def _prepare_withholding_vals(self):
        return {
            "journal_id": self.journal_id.id,
            "ref": self.document_number,
            "date": self.issue_date,
            "l10n_ec_electronic_authorization": self.electronic_authorization,
            "move_type": "entry",
            "l10n_latam_document_type_id": self.env.ref("l10n_ec.ec_dt_07").id,
            "partner_id": self.partner_id.id,
        }

    def _try_reconcile_withholding_moves(self, withholding, invoices, account_type):
        assert account_type in ["asset_receivable", "liability_payable"], _(
            "Account type not supported, this must be receivable or payable"
        )
        aml_to_reconcile = invoices.line_ids.filtered(
            lambda line: line.account_id.account_type == account_type
        )
        aml_to_reconcile += withholding.line_ids.filtered(
            lambda line: line.account_id.account_type == account_type
        )
        aml_to_reconcile.reconcile()
        withholding_lines = withholding.line_ids.filtered(
            lambda line: line.tax_repartition_line_id
        )
        withholding_lines.write({"l10n_ec_withhold_id": withholding.id})
        return True


class WizardAbstractWithholdLine(models.AbstractModel):
    _name = "l10n_ec.wizard.abstract.withhold.line"
    _description = "Wizard Abstract withhold line"

    tax_group_withhold_id = fields.Many2one(
        comodel_name="account.tax.group",
        string="Withholding Type",
    )
    tax_withhold_id = fields.Many2one(
        comodel_name="account.tax",
        string="Withholding tax",
    )
    base_amount = fields.Float(string="Amount Base", readonly=True)
    withhold_amount = fields.Float(
        string="Amount Withhold",
        compute="_compute_withholding_amount",
        store=True,
    )
    invoice_id = fields.Many2one("account.move")

    @api.onchange("invoice_id", "tax_group_withhold_id")
    def _onchange_withholding_base(self):
        for line in self:
            if line.tax_group_withhold_id.l10n_ec_type in [
                "withhold_income_sale",
                "withhold_income_purchase",
            ]:
                line.base_amount = abs(line.invoice_id.amount_untaxed_signed)
            elif line.tax_group_withhold_id.l10n_ec_type in [
                "withhold_vat_sale",
                "withhold_vat_purchase",
            ]:
                line.base_amount = abs(line.invoice_id.amount_tax_signed)

    @api.depends("invoice_id", "tax_withhold_id", "base_amount")
    def _compute_withholding_amount(self):
        for line in self:
            line.withhold_amount = abs(
                line.base_amount * line.tax_withhold_id.amount / 100
            )

    @api.onchange("tax_group_withhold_id")
    def onchange_tax_group_withhold(self):
        self.tax_withhold_id = False

    def _get_withholding_line_vals(self, wizard):
        taxes_data = self.tax_withhold_id.compute_all(self.base_amount)
        tax_vals = []
        for tax_data in taxes_data.get("taxes"):
            tax_vals.append(self._prepare_amount_vals(wizard, tax_data))
            tax_vals.append(self._prepare_basis_vals(wizard, tax_data))
            tax_vals.append(self._prepare_basis_counterpart_vals(wizard, tax_data))
        return tax_vals

    def _prepare_amount_vals(self, wizard, tax_data):
        debit = credit = 0.0
        if self.invoice_id.move_type == "out_invoice":
            debit = abs(self.withhold_amount)
        if self.invoice_id.move_type == "in_invoice":
            credit = abs(self.withhold_amount)

        return {
            "partner_id": wizard.partner_id.id,
            "quantity": 1.0,
            "price_unit": abs(self.withhold_amount),
            "account_id": tax_data.get("account_id"),
            "name": "RET " + wizard.document_number,
            "debit": debit,
            "credit": credit,
            "tax_tag_ids": [(6, 0, tax_data.get("tag_ids"))],
            "tax_base_amount": tax_data.get("base"),
            "tax_repartition_line_id": tax_data.get("tax_repartition_line_id"),
            "l10n_ec_invoice_withhold_id": self.invoice_id.id,
        }

    def _prepare_basis_vals(self, wizard, tax_data):
        debit = credit = 0.0
        if self.invoice_id.move_type == "out_invoice":
            credit = abs(tax_data.get("base"))
        if self.invoice_id.move_type == "in_invoice":
            debit = abs(tax_data.get("base"))
        return {
            "partner_id": wizard.partner_id.id,
            "quantity": 1.0,
            "price_unit": abs(tax_data.get("base")),
            "account_id": tax_data.get("account_id"),
            "name": "RET " + wizard.document_number,
            "debit": debit,
            "credit": credit,
            "tax_ids": [(6, 0, self.tax_withhold_id.ids)],
            "tax_tag_ids": [],
        }

    def _prepare_basis_counterpart_vals(self, wizard, tax_data):
        debit = credit = 0.0
        if self.invoice_id.move_type == "out_invoice":
            debit = abs(tax_data.get("base"))
        if self.invoice_id.move_type == "in_invoice":
            credit = abs(tax_data.get("base"))
        return {
            "partner_id": wizard.partner_id.id,
            "quantity": 1.0,
            "price_unit": abs(tax_data.get("base")),
            "account_id": tax_data.get("account_id"),
            "name": _("Counterpart RET ") + wizard.document_number,
            "debit": debit,
            "credit": credit,
            "tax_ids": [],
            "tax_tag_ids": [],
        }
