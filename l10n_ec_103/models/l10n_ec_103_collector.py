"""Collector of Form 103 boxes from posted moves of the period.

Single source of truth for every derivable box of the SRI *Formulario 103
Retenciones en la Fuente*: the collectors turn ``account.move`` records
(``state = 'posted'``, ``company_id``, ``move.date`` inside the reported
month) into per-box amounts, and the wizard renders them as concepto→valor
pairs for the portal upload (XML/JSON guide).

The mapping rule is the same one the 104 module proved: **tags decide, the
collector only adds.** The EC chart template maps every income-withholding
tax to its boxes through the ``Reporte 103`` tags on the repartition lines
(e.g. ``tax_withhold_profit_303`` carries 303 on the base and 353 on the
tax, invoice and refund sides each with their own tags). No rate is
therefore hardcoded here. Boxes the chart carries no tag for -- the
subtotals (349/399, 497/498), the totals (499/501) and the payment section
-- are computed or manual.

Full logic lands in T2 (residents), T3 (non-residents and totals) and T4
(wizard). This stub exists so the addon installs and the wizard has a
collection seam to call.
"""

import re

from odoo import models

#: ``303 (Reporte 103)`` -> ``303``. Tags of other reports never match.
#: Four digits admit the 3xxx concept boxes (3030, 3120, ...).
TAG_RE = re.compile(r"^(\d{3,4}) \(Reporte 103\)$")

WITHHOLD_MOVE_TYPES = ("in_invoice", "in_refund")


class L10nEc103Collector(models.AbstractModel):
    _name = "l10n.ec.103.collector"
    _description = "Ecuadorian Form 103 collector (stub, see T2-T4)"

    def _l10n_ec_103_collect(self, company, date_start, date_finish):
        """Collect per-box amounts for the reported month.

        :param company: ``res.company`` the return is filed for.
        :param date_start: first day of the reported month.
        :param date_finish: last day of the reported month.
        :returns: ``dict`` mapping box number (``str``) to amount (``float``).
        :raises NotImplementedError: until T4 composes the blocks.
        """
        raise NotImplementedError("l10n_ec_103 blocks compose in T4")

    def _l10n_ec_103_collect_residentes(self, company, date_start, date_finish):
        """Collect the resident boxes (3xx) for the month.

        Every box the chart tags is read off the posted vendor bills and
        credit notes: base lines carry the base boxes (302...), tax lines
        carry the withheld boxes (352...), invoice and refund sides each
        with their own tags. Core reads them with positive formulas
        (``303 (Reporte 103)``), so the collector adds every tagged
        balance uniformly: bills count positive, vendor credit notes
        count negative, and the net boxes come out with no special case.

        One split the 104 never needed: withholding taxes carry negative
        rates, so their tax lines post with the opposite sign of the base
        lines. Base (product) lines therefore add while tax lines negate;
        the refund side mirrors both, keeping the net exact. Only boxes
        starting with 3 belong here -- the 4xx non-resident boxes live in
        :meth:`_l10n_ec_103_collect_exterior`. The subtotals the chart
        carries no tag for (349/399) sum each side: 349 over the base
        legs, 399 over the withheld legs.
        """
        boxes, base_by_digit, tax_by_digit = self._l10n_ec_103_collect_all(
            company, date_start, date_finish
        )
        out = {box: amount for box, amount in boxes.items() if box[0] == "3"}
        out["349"] = base_by_digit.get("3", 0.0)
        out["399"] = tax_by_digit.get("3", 0.0)
        return {box: company.currency_id.round(amount) for box, amount in out.items()}

    def _l10n_ec_103_collect_exterior(self, company, date_start, date_finish):
        """Collect the non-resident boxes (4xx) for the month.

        Mirror of :meth:`_l10n_ec_103_collect_residentes` over the boxes
        starting with 4 (402-433 bases, 452-482 withheld). The user
        classifies by choosing the concept tax (sustento + box); treaty
        and haven classification per payee stays manual in v1 (see the
        roadmap). The subtotals the chart carries no tag for (497/498)
        sum each side like 349/399 do.
        """
        boxes, base_by_digit, tax_by_digit = self._l10n_ec_103_collect_all(
            company, date_start, date_finish
        )
        out = {box: amount for box, amount in boxes.items() if box[0] == "4"}
        out["497"] = base_by_digit.get("4", 0.0)
        out["498"] = tax_by_digit.get("4", 0.0)
        return {box: company.currency_id.round(amount) for box, amount in out.items()}

    def _l10n_ec_103_collect_totals(
        self, company, residentes, exterior, carryover=None
    ):
        """Total the return: 499, 500 and 501.

        499 adds both withheld subtotals (399 + 498); the base subtotals
        (349 + 497) are informative and stay out of the tax total. 500
        (undistributed-profit advance compensation) is case-file state
        that only the dividends reading can supply, so it travels in
        ``carryover`` defaulting to 0.0; 501 is 499 − 500.
        """
        carryover = carryover or {}
        boxes = {
            "499": residentes.get("399", 0.0) + exterior.get("498", 0.0),
            "500": carryover.get("500", 0.0),
        }
        boxes["501"] = boxes["499"] - boxes["500"]
        return {box: company.currency_id.round(amount) for box, amount in boxes.items()}

    def _l10n_ec_103_collect_all(self, company, date_start, date_finish):
        """All tagged boxes plus base/tax legs keyed by first digit.

        Returns ``(boxes, base_by_digit, tax_by_digit)`` over the posted
        vendor bills and credit notes of the period, so the resident and
        exterior collectors slice one pass instead of re-reading.
        """
        boxes = {}
        base_by_digit = {}
        tax_by_digit = {}
        moves = self.env["account.move"].search(
            [
                ("company_id", "=", company.id),
                ("move_type", "in", list(WITHHOLD_MOVE_TYPES)),
                ("state", "=", "posted"),
                ("date", ">=", date_start),
                ("date", "<=", date_finish),
            ]
        )
        for line in moves.mapped("line_ids"):
            is_tax_line = bool(line.tax_line_id)
            for tag in line.tax_tag_ids:
                match = TAG_RE.match(tag.name or "")
                if not match:
                    continue
                box = match.group(1)
                amount = -line.balance if is_tax_line else line.balance
                boxes[box] = boxes.get(box, 0.0) + amount
                leg = tax_by_digit if is_tax_line else base_by_digit
                leg[box[0]] = leg.get(box[0], 0.0) + amount
        return boxes, base_by_digit, tax_by_digit
