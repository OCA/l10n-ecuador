from odoo import fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    l10n_ec_type_credit_note = fields.Selection(
        [("discount", "Discount"), ("return", "Return")],
        string="Credit note type",
        default="discount",
    )

    def action_reverse(self):
        action = super().action_reverse()
        if (
            self.company_id.account_fiscal_country_id.code == "EC"
            and self.move_type == "out_invoice"
        ):
            action["views"] = [
                (
                    self.env.ref(
                        "l10n_ec_credit_note.view_account_invoice_refund_sale"
                    ).id,
                    "form",
                )
            ]
        return action

    def _get_account_product_line(self, product_id, l10n_ec_type_credit_note):
        self.ensure_one()
        product = self.env["product.product"].browse(product_id)
        account = self.env["account.account"]
        if product:
            account = (
                product.l10n_ec_property_account_return_id
                if l10n_ec_type_credit_note == "return"
                else product.l10n_ec_property_account_discount_id
            )
            if not account:
                account = (
                    product.categ_id.l10n_ec_property_account_return_id
                    if l10n_ec_type_credit_note == "return"
                    else product.categ_id.l10n_ec_property_account_discount_id
                )
        if not account:
            account = (
                self.company_id.l10n_ec_property_account_return_id
                if l10n_ec_type_credit_note == "return"
                else self.company_id.l10n_ec_property_account_discount_id
            )

        return account

    def _stock_account_prepare_anglo_saxon_out_lines_vals(self):
        discount_credit_notes = self.filtered(
            lambda x: x.move_type in ["in_refund", "out_refund"]
            and x.l10n_ec_type_credit_note == "discount"
        )
        return super(
            AccountMove, self - discount_credit_notes
        )._stock_account_prepare_anglo_saxon_out_lines_vals()

    def copy_data(self, default=None):
        res = super().copy_data(default=default)
        if self.company_id.country_code != "EC":
            return res
        for copy_vals in res:
            l10n_ec_type_credit_note = copy_vals.get("l10n_ec_type_credit_note")
            move_type = copy_vals.get("move_type")
            if (
                self._context.get("move_reverse_cancel")
                and move_type == "out_refund"
                and l10n_ec_type_credit_note == "discount"
            ):
                copy_vals["line_ids"] = [
                    line_vals
                    for line_vals in copy_vals["line_ids"]
                    if line_vals[0] != 0 or line_vals[2].get("display_type") != "cogs"
                ]
            if move_type == "out_refund":
                for line_vals in copy_vals["line_ids"]:
                    if line_vals[2] and line_vals[2].get("display_type") == "product":
                        new_account = self._get_account_product_line(
                            line_vals[2]["product_id"],
                            copy_vals.get("l10n_ec_type_credit_note"),
                        )
                        if new_account:
                            line_vals[2]["account_id"] = new_account.id
        return res
