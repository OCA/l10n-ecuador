from odoo import api, models


class AccountTax(models.Model):
    _inherit = "account.tax"

    @api.model
    def _prepare_base_line_grouping_key(self, base_line):
        """Split the generated tax lines of a withholding per invoice and tax support.

        In 17.0 this was done by extending ``account.move.line.tax_key`` and
        ``compute_all_tax``. Those were Enterprise-only internals of
        ``account`` -- non-stored computes hidden from field access rights,
        read back by ``_sync_dynamic_line(existing_key_fname='tax_key')`` to
        decide which base lines share a tax line -- and they no longer exist
        in 19.0.

        ``_prepare_base_line_grouping_key`` is the 19.0 seam that builds the
        very same accounting grouping key: ``_prepare_tax_lines`` keys its
        aggregation on it, writes it onto the tax lines it creates
        (``tax_lines_to_add = [{**grouping_key, **values}]``) and matches
        existing tax lines against it. So adding the withholding keys here
        reproduces 17.0 byte for byte. See ``hr_expense`` for the same
        extension point, and ``l10n_ar_withholding`` for the same guard.

        Amounts are unaffected: the withheld amount sits on the withholding
        basis line (``price_total - price_subtotal``), not on the tax line, so
        a tax line split changes the number of tax lines and never their sum.
        """
        res = super()._prepare_base_line_grouping_key(base_line)
        record = base_line["record"]
        if isinstance(record, models.Model) and record._name == "account.move.line":
            self._l10n_ec_add_withhold_grouping_key(res, record)
        return res

    @api.model
    def _prepare_tax_line_repartition_grouping_key(self, tax_line):
        """Read the withholding keys back off an existing tax line.

        The two grouping-key builders must stay consistent with each other
        (see ``_prepare_tax_line_repartition_grouping_key``'s docstring),
        otherwise every recompute would fail to match the tax lines it just
        generated and delete/recreate them.
        """
        res = super()._prepare_tax_line_repartition_grouping_key(tax_line)
        record = tax_line["record"]
        if isinstance(record, models.Model) and record._name == "account.move.line":
            self._l10n_ec_add_withhold_grouping_key(res, record)
        return res

    @api.model
    def _l10n_ec_add_withhold_grouping_key(self, grouping_key, line):
        """Add the withholding dimensions to ``grouping_key``, in place.

        Only the basis lines of a withholding carry an invoice, so ordinary
        invoices, purchases and refunds keep the base grouping key untouched.
        """
        if not line.l10n_ec_invoice_withhold_id:
            return
        grouping_key["l10n_ec_invoice_withhold_id"] = line.l10n_ec_invoice_withhold_id.id
        grouping_key["l10n_ec_tax_support"] = line._get_l10n_ec_tax_support()
