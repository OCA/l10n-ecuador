"""Reconcile the 104 aggregates against the ATS blocks, per period.

The ATS and the 104 read the same posted moves and must agree where their
definitions overlap -- and disagree loudly where they do not. The one trap
this module exists for: ATS ``totalVentas`` is **gross** (a credit note
contributes its magnitude, the document type telling the SRI the
difference) while the 104's 419 is **net**. Comparing them directly drifts
by twice the credit notes every month with returns, so the reconciliation
adjusts for that instead of asserting an equality the sources contradict:

* Check A (net vs net): Σ ATS ``ventasEstab`` (signed net per
  establishment) against the 104's 419.
* Check B (gross vs gross): Σ ATS ``montoIva`` (absolute per row) against
  the 104's 429, minus its 423 plus its 424 adjustments (which have no ATS
  counterpart), plus twice the credit-note tax of the period.

A period the ATS cannot build is refused with the ATS errors aggregated --
a partial ATS side would reconcile against a file the company never had.
A period with no sales moves at all reconciles trivially to zero on both
sides without touching the ATS collectors.
"""

from odoo import models
from odoo.exceptions import UserError

#: 104 tax boxes whose refund legs rebuild the gross ATS side.
NC_TAX_BOXES = ("421", "422", "430", "445")


class L10nEc104AtsReconcile(models.AbstractModel):
    _name = "l10n.ec.104.ats.reconciler"
    _description = "Ecuadorian Form 104 vs ATS reconciliation"

    def check_period(self, company, date_start, date_finish):
        """Reconcile one period, returning the verdict per check.

        :returns: ``{"checks": [...], "match": bool}`` where each check
            carries ``check``, ``ats``, ``form_104``, ``diff`` (ats − 104)
            and ``verdict`` (``"match"``/``"drift"``).
        :raises UserError: with every ATS problem found, not the first; no
            check is reported and nothing is presented as reconciled.
        """
        if not self._l10n_ec_104_has_sales(company, date_start, date_finish):
            zero_checks = [
                self._l10n_ec_104_check("A", 0.0, 0.0, company),
                self._l10n_ec_104_check("B", 0.0, 0.0, company),
            ]
            return {"checks": zero_checks, "match": True}
        ats = self.env["l10n.ec.ats.collector"]
        imp = self.env["l10n.ec.104.collector"]
        ventas_rows, errors = ats.collect_ventas_with_errors(
            company, date_start, date_finish
        )
        est_rows, est_errors = ats.collect_ventas_establecimiento_with_errors(
            company, date_start, date_finish
        )
        errors.extend(est_errors)
        if not errors:
            _header, header_errors = ats.collect_iva_header_with_errors(
                ventas_rows, est_rows
            )
            errors.extend(header_errors)
        if errors:
            raise UserError(self._l10n_ec_104_refusal(errors))
        boxes = imp._l10n_ec_104_collect_ventas(company, date_start, date_finish)
        currency = company.currency_id
        ats_net = currency.round(sum(row.get("ventasEstab", 0.0) for row in est_rows))
        ats_iva = currency.round(sum(row.get("montoIva", 0.0) for row in ventas_rows))
        credit_note_tax = self._l10n_ec_104_credit_note_tax(
            company, date_start, date_finish
        )
        expected_iva = currency.round(
            boxes.get("429", 0.0)
            - boxes.get("423", 0.0)
            + boxes.get("424", 0.0)
            + 2 * credit_note_tax
        )
        checks = [
            self._l10n_ec_104_check("A", ats_net, boxes.get("419", 0.0), company),
            self._l10n_ec_104_check("B", ats_iva, expected_iva, company),
        ]
        return {
            "checks": checks,
            "match": all(check["verdict"] == "match" for check in checks),
        }

    def _l10n_ec_104_has_sales(self, company, date_start, date_finish):
        """Whether any posted customer move falls in the period."""
        return bool(
            self.env["account.move"].search_count(
                [
                    ("company_id", "=", company.id),
                    ("move_type", "in", ["out_invoice", "out_refund"]),
                    ("state", "=", "posted"),
                    ("date", ">=", date_start),
                    ("date", "<=", date_finish),
                ]
            )
        )

    def _l10n_ec_104_credit_note_tax(self, company, date_start, date_finish):
        """Absolute tax magnitudes on the period's customer credit notes.

        The refund legs the 104 nets away and the ATS sums up: reading them
        back is what makes check B compare gross with gross.
        """
        imp = self.env["l10n.ec.104.collector"]
        moves = self.env["account.move"].search(
            [
                ("company_id", "=", company.id),
                ("move_type", "=", "out_refund"),
                ("state", "=", "posted"),
                ("date", ">=", date_start),
                ("date", "<=", date_finish),
            ]
        )
        total = 0.0
        for line in moves.mapped("line_ids"):
            if any(imp._l10n_ec_104_line_has_box(line, box) for box in NC_TAX_BOXES):
                total += line.balance
        return company.currency_id.round(total)

    def _l10n_ec_104_check(self, name, ats_amount, imp_amount, company):
        """One named check, matched on rounded equality."""
        currency = company.currency_id
        ats_amount = currency.round(ats_amount)
        imp_amount = currency.round(imp_amount)
        diff = currency.round(ats_amount - imp_amount)
        return {
            "check": name,
            "ats": ats_amount,
            "form_104": imp_amount,
            "diff": diff,
            "verdict": "match" if diff == 0.0 else "drift",
        }

    def _l10n_ec_104_refusal(self, errors):
        """Aggregate ATS problems into one refusal naming each document."""
        lines = []
        for number, error in enumerate(errors, start=1):
            move = error.get("move")
            where = move.display_name if move else "header"
            lines.append(
                f"{number}. [{where}] {error.get('field')}: {error.get('message')}"
            )
        return self.env._(
            "104 vs ATS reconciliation refused:\n%(problems)s\n"
            "Nothing was reconciled and nothing was assumed.",
            problems="\n".join(lines),
        )
