"""Collector of Form 104 (IVA) boxes from posted moves of the period.

Single source of truth for every derivable box of the SRI *Formulario
Impuesto al Valor Agregado*: the collectors turn ``account.move`` records
(``state = 'posted'``, ``company_id``, ``move.date`` inside the reported
month) into per-box amounts, and the wizard renders them over the 104 report
of Odoo core (``odoo/addons/l10n_ec``, engine ``tax_tags``).

What this module never reimplements (S2): the ~110 report lines core already
computes from the ``Reporte 104`` tax tags (sales/purchase summaries, 5%
materials, 423/424 and 526/527 adjustments, perception/withholding frame).
Those boxes are read, never recalculated. What it adds is the layer core does
not ship: the variable-rate boxes (410/420/430, 530/533/534), the credit-sale
settlement (480-485/499), the slip counts (111/113/115/117/119), the
proportionality factor (563) with its suggested credit (564/565), and the
traceability from every prefilled box back to its documents.

One mapping rule governs the whole collector: **tags decide, the collector
only adds.** The EC chart template already maps every sales and purchase tax
to its 104 boxes through the ``Reporte 104`` tags on the repartition lines
(e.g. ``tax_vat_15_411_goods`` carries 401/411 on the base and 421 on the
tax, invoice and refund sides each with their own tags). No rate is therefore
hardcoded here: the collectors aggregate the signed balances of the posted
lines carrying those tags, and compute the boxes the chart carries no tag
for -- the totals (409/419/429) and the rate-difference adjustments
(423/424).
"""

import re

from odoo import models

#: ``401 (Reporte 104)`` -> ``401``. Tags of other reports never match.
TAG_RE = re.compile(r"^(\d{3}) \(Reporte 104\)$")

SALES_MOVE_TYPES = ("out_invoice", "out_refund")
PURCHASE_MOVE_TYPES = ("in_invoice", "in_refund")

#: Boxes summed into the gross total 409. 425 (5% materials) sits inside
#: the sales section of the form, so the section total covers it. 410 reads
#: variable-rate taxes the chart does not ship yet, so it stays 0.0 until
#: the chart publishes them.
GROSS_BOXES = (
    "401",
    "402",
    "403",
    "404",
    "405",
    "406",
    "407",
    "408",
    "410",
    "425",
)
#: Boxes summed into the net total 419 (420 and 435, same remarks as 410
#: and 425: 435 is the 5% net box inside the section, 420 reads variable-rate
#: taxes the chart does not ship yet).
NET_BOXES = (
    "411",
    "412",
    "413",
    "414",
    "415",
    "416",
    "417",
    "418",
    "420",
    "435",
)
#: Tax boxes summed into the generated-tax total 429. 424 (adjustment in
#: favor) subtracts; 430 reads variable-rate taxes the chart does not ship
#: yet. 453 (credit notes to offset next month) is a manual carryover and is
#: not collected.
TAX_BOXES_ADD = ("421", "422", "423", "430", "445")
TAX_BOXES_SUB = ("424",)
#: Variable-rate sales boxes gating box 423 (see
#: ``_l10n_ec_104_rate_adjustment``).
VARIABLE_SALES_BOXES = ("410", "420", "430")
#: Boxes summed into the gross purchase total 509. 540 (5% materials)
#: sits inside the purchase section of the form, so the section total covers
#: it. 530 reads variable-rate taxes the chart does not ship yet.
PURCHASE_GROSS_BOXES = (
    "500",
    "501",
    "502",
    "503",
    "504",
    "505",
    "506",
    "507",
    "508",
    "530",
    "540",
)
#: Boxes summed into the net purchase total 519 (533 and 550, same remarks
#: as 530 and 540).
PURCHASE_NET_BOXES = (
    "510",
    "511",
    "512",
    "513",
    "514",
    "515",
    "516",
    "517",
    "518",
    "533",
    "550",
)
#: Tax boxes summed into the purchase-tax total 529. 527 (negative
#: adjustment) subtracts; 534 reads variable-rate taxes the chart does not
#: ship yet.
PURCHASE_TAX_BOXES_ADD = (
    "520",
    "521",
    "522",
    "523",
    "524",
    "525",
    "526",
    "534",
    "560",
)
PURCHASE_TAX_BOXES_SUB = ("527",)


class L10nEc104Collector(models.AbstractModel):
    _name = "l10n.ec.104.collector"
    _description = "Ecuadorian Form 104 collector"

    def _l10n_ec_104_collect(self, company, date_start, date_finish):
        """Collect per-box amounts for the reported month.

        :param company: ``res.company`` the return is filed for.
        :param date_start: first day of the reported month.
        :param date_finish: last day of the reported month.
        :returns: ``dict`` mapping box number (``str``) to amount (``float``).
        :raises NotImplementedError: until T5 composes the blocks.
        """
        raise NotImplementedError("l10n_ec_104 blocks compose in T5")

    def _l10n_ec_104_collect_ventas(self, company, date_start, date_finish):
        """Collect the sales boxes (401-454) for the reported month.

        Every box the chart tags is read off the posted customer invoices
        and credit notes: invoice base lines carry the gross tags (401…),
        refund base lines carry the net tags (411…) only, and tax lines
        carry the generated-tax tags (421…). Core reads them with the same
        sign (``-401 (Reporte 104)`` on both sides), so the collector
        negates every tagged balance uniformly: invoice credits count
        positive, refund debits count negative, and the net boxes come out
        as gross minus refunds with no special case.

        Boxes the chart carries no tag for are computed: 409/419 as the sum
        of their buckets, 429 as 421+422+423-424+430+445, and 423/424 from
        the credit notes linked to their invoice (``reversed_entry_id``)
        whose rate differs (see ``_l10n_ec_104_rate_adjustment``).
        """
        boxes = self._l10n_ec_104_empty_sales_boxes()
        moves = self.env["account.move"].search(
            [
                ("company_id", "=", company.id),
                ("move_type", "in", list(SALES_MOVE_TYPES)),
                ("state", "=", "posted"),
                ("date", ">=", date_start),
                ("date", "<=", date_finish),
            ]
        )
        for line in moves.mapped("line_ids"):
            for tag in line.tax_tag_ids:
                match = TAG_RE.match(tag.name or "")
                if not match:
                    continue
                box = match.group(1)
                boxes[box] = boxes.get(box, 0.0) - line.balance
        for refund in moves.filtered(
            lambda m: m.move_type == "out_refund" and m.reversed_entry_id
        ):
            self._l10n_ec_104_rate_adjustment(
                boxes,
                refund,
                lower_box="423",
                higher_box="424",
                variable_boxes=VARIABLE_SALES_BOXES,
            )
        boxes["409"] = sum(boxes[box] for box in GROSS_BOXES)
        boxes["419"] = sum(boxes[box] for box in NET_BOXES)
        boxes["429"] = sum(boxes[box] for box in TAX_BOXES_ADD) - sum(
            boxes[box] for box in TAX_BOXES_SUB
        )
        return {box: company.currency_id.round(amount) for box, amount in boxes.items()}

    def _l10n_ec_104_empty_sales_boxes(self):
        """Every box the sales block owns, at zero."""
        return {
            box: 0.0
            for box in (
                *GROSS_BOXES,
                *NET_BOXES,
                "421",
                "422",
                "423",
                "424",
                "425",
                "430",
                "431",
                "434",
                "435",
                "441",
                "444",
                "445",
                "454",
                "409",
                "419",
                "429",
            )
        }

    def _l10n_ec_104_collect_compras(self, company, date_start, date_finish):
        """Collect the purchase boxes (500-560) for the reported month.

        Mirror of ``_l10n_ec_104_collect_ventas`` with purchase signs:
        vendor bills are debit-positive and core reads the purchase boxes
        with positive formulas (``500 (Reporte 104)``), so the collector
        adds every tagged balance uniformly: bills count positive, vendor
        credit notes count negative, and the net boxes come out as gross
        minus notes with no special case.

        Boxes the chart carries no tag for are computed: 509/519 as the sum
        of their buckets (540/550 inside the section, like 425/435 on the
        sales side), 529 as 520+521+522+523+524+525+526-527+534+560, and
        526/527 from the vendor credit notes linked to their bill
        (``reversed_entry_id``) whose rate differs.
        """
        boxes = self._l10n_ec_104_empty_compras_boxes()
        moves = self.env["account.move"].search(
            [
                ("company_id", "=", company.id),
                ("move_type", "in", list(PURCHASE_MOVE_TYPES)),
                ("state", "=", "posted"),
                ("date", ">=", date_start),
                ("date", "<=", date_finish),
            ]
        )
        for line in moves.mapped("line_ids"):
            for tag in line.tax_tag_ids:
                match = TAG_RE.match(tag.name or "")
                if not match:
                    continue
                box = match.group(1)
                boxes[box] = boxes.get(box, 0.0) + line.balance
        for refund in moves.filtered(
            lambda m: m.move_type == "in_refund" and m.reversed_entry_id
        ):
            self._l10n_ec_104_rate_adjustment(
                boxes, refund, lower_box="526", higher_box="527"
            )
        boxes["509"] = sum(boxes[box] for box in PURCHASE_GROSS_BOXES)
        boxes["519"] = sum(boxes[box] for box in PURCHASE_NET_BOXES)
        boxes["529"] = sum(boxes[box] for box in PURCHASE_TAX_BOXES_ADD) - sum(
            boxes[box] for box in PURCHASE_TAX_BOXES_SUB
        )
        return {box: company.currency_id.round(amount) for box, amount in boxes.items()}

    def _l10n_ec_104_empty_compras_boxes(self):
        """Every box the purchase block owns, at zero."""
        return {
            box: 0.0
            for box in (
                *PURCHASE_GROSS_BOXES,
                *PURCHASE_NET_BOXES,
                "520",
                "521",
                "522",
                "523",
                "524",
                "525",
                "526",
                "527",
                "531",
                "532",
                "534",
                "535",
                "541",
                "542",
                "543",
                "544",
                "545",
                "554",
                "555",
                "560",
                "509",
                "519",
                "529",
            )
        }

    def _l10n_ec_104_collect_liquidacion(
        self, company, date_start, date_finish, ventas, compras, carryover=None
    ):
        """Settle the month: 480-499, 563-565, 601-699 and 799-859.

        482 carries 429 over. 484 defaults to the VAT of the cash sales:
        the guide asks for *at least* the VAT of box 480, plus the credit
        VAT *as applicable* -- unknowable from the moves alone, so the
        prefill books the cash VAT and carries the rest to 485 (= 482-484).
        499 is 483+484 with 483 (prior 485) coming from ``carryover``.
        Cash versus credit follows the invoice payment term: no term or a
        single zero-day line settles cash (480), anything else settles on
        credit (481). Only customer invoices classify; credit notes are
        already netted in the 411… boxes.

        563 follows the guide formula literally,
        (411+412+420+415+416+417+418)/419 -- 435 is not in the numerator
        -- with 1.0 when 419 is zero (no sales to apportion, documented
        default, editable as the portal marks it suggested). 564 applies
        the factor to the creditable VAT paid
        (520+521+534+560+523+524+525+526-527; 522 carries no credit right
        and stays out), 565 is the difference. 601/602 are mutually
        exclusive by construction.

        609 and 721…731 read the tags the withhold taxes publish (zero
        until the withhold flow records them). 699 is 620+621, 801 is
        799-800-802, 859 is 699+801 -- the three formulas the SRI layout
        sheet states. Every other box of the perception/withholding
        sections (prior balances, compensations, sector benefits, merger,
        public-sector unpaid) is cross-period or case-file state: it
        defaults to 0.0 here and travels in ``carryover`` when the caller
        (T5 wizard) collects it from the user.
        """
        carryover = carryover or {}
        boxes = self._l10n_ec_104_empty_liquidacion_boxes()
        contado_base, contado_tax, credito_base, credito_tax = (
            self._l10n_ec_104_cash_credit_split(company, date_start, date_finish)
        )
        boxes["480"] = contado_base
        boxes["481"] = credito_base
        boxes["482"] = ventas.get("429", 0.0)
        boxes["483"] = carryover.get("483", 0.0)
        boxes["484"] = contado_tax
        boxes["485"] = boxes["482"] - boxes["484"]
        boxes["499"] = boxes["483"] + boxes["484"]
        total_ventas = ventas.get("419", 0.0)
        if total_ventas:
            boxes["563"] = (
                sum(
                    ventas.get(box, 0.0)
                    for box in ("411", "412", "420", "415", "416", "417", "418")
                )
                / total_ventas
            )
        else:
            boxes["563"] = 1.0
        credit_base = sum(
            compras.get(box, 0.0)
            for box in ("520", "521", "534", "560", "523", "524", "525", "526")
        ) - compras.get("527", 0.0)
        boxes["564"] = credit_base * boxes["563"]
        boxes["565"] = credit_base - boxes["564"]
        if boxes["499"] - boxes["564"] > 0:
            boxes["601"] = boxes["499"] - boxes["564"]
        elif boxes["564"] - boxes["499"] > 0:
            boxes["602"] = boxes["564"] - boxes["499"]
        boxes["609"] = -sum(
            line.balance
            for line in self._l10n_ec_104_tagged_sales_lines(
                company, date_start, date_finish, "609"
            )
        )
        boxes["620"] = (
            boxes["601"]
            - boxes["602"]
            - carryover.get("603", 0.0)
            - carryover.get("604", 0.0)
            - carryover.get("605", 0.0)
            - carryover.get("606", 0.0)
            - carryover.get("607", 0.0)
            - carryover.get("608", 0.0)
            - boxes["609"]
            + carryover.get("610", 0.0)
            + carryover.get("611", 0.0)
            + carryover.get("612", 0.0)
            + carryover.get("613", 0.0)
            + carryover.get("614", 0.0)
        )
        boxes["699"] = boxes["620"] + carryover.get("621", 0.0)
        for withhold_box in ("721", "723", "725", "727", "729", "731"):
            boxes[withhold_box] = sum(
                line.balance
                for line in self._l10n_ec_104_tagged_purchase_lines(
                    company, date_start, date_finish, withhold_box
                )
            )
        boxes["799"] = sum(
            boxes[box] for box in ("721", "723", "725", "727", "729", "731")
        )
        boxes["801"] = (
            boxes["799"] - carryover.get("800", 0.0) - carryover.get("802", 0.0)
        )
        boxes["859"] = boxes["699"] + boxes["801"]
        return {box: company.currency_id.round(amount) for box, amount in boxes.items()}

    def _l10n_ec_104_empty_liquidacion_boxes(self):
        """Every box the settlement owns, at zero."""
        return {
            box: 0.0
            for box in (
                "480",
                "481",
                "482",
                "483",
                "484",
                "485",
                "486",
                "487",
                "499",
                "563",
                "564",
                "565",
                "601",
                "602",
                "609",
                "620",
                "699",
                "721",
                "723",
                "725",
                "727",
                "729",
                "731",
                "799",
                "801",
                "859",
            )
        }

    def _l10n_ec_104_cash_credit_split(self, company, date_start, date_finish):
        """Split the month's nonzero-rated sales into cash and credit.

        Returns ``(contado_base, contado_tax, credito_base, credito_tax)``
        over the posted customer invoices (credit notes excluded, already
        netted): ``contado`` when the payment term is missing or a single
        zero-day line, ``credito`` otherwise. Bases read the gross nonzero
        boxes (401/402/410/425), taxes read 421/422/430/445.
        """
        contado_base = contado_tax = credito_base = credito_tax = 0.0
        moves = self.env["account.move"].search(
            [
                ("company_id", "=", company.id),
                ("move_type", "=", "out_invoice"),
                ("state", "=", "posted"),
                ("date", ">=", date_start),
                ("date", "<=", date_finish),
            ]
        )
        for move in moves:
            term_lines = move.invoice_payment_term_id.line_ids
            contado = not term_lines or (
                len(term_lines) == 1 and term_lines[0].nb_days == 0
            )
            for line in move.line_ids:
                for tag in line.tax_tag_ids:
                    match = TAG_RE.match(tag.name or "")
                    if not match:
                        continue
                    box = match.group(1)
                    if box in ("401", "402", "410", "425"):
                        if contado:
                            contado_base -= line.balance
                        else:
                            credito_base -= line.balance
                    elif box in ("421", "422", "430", "445"):
                        if contado:
                            contado_tax -= line.balance
                        else:
                            credito_tax -= line.balance
        return contado_base, contado_tax, credito_base, credito_tax

    def _l10n_ec_104_tagged_sales_lines(self, company, date_start, date_finish, box):
        """Posted customer-move lines carrying the ``box`` tag."""
        moves = self.env["account.move"].search(
            [
                ("company_id", "=", company.id),
                ("move_type", "in", list(SALES_MOVE_TYPES)),
                ("state", "=", "posted"),
                ("date", ">=", date_start),
                ("date", "<=", date_finish),
            ]
        )
        return moves.mapped("line_ids").filtered(
            lambda line: self._l10n_ec_104_line_has_box(line, box)
        )

    def _l10n_ec_104_tagged_purchase_lines(self, company, date_start, date_finish, box):
        """Posted vendor-move lines carrying the ``box`` tag."""
        moves = self.env["account.move"].search(
            [
                ("company_id", "=", company.id),
                ("move_type", "in", list(PURCHASE_MOVE_TYPES)),
                ("state", "=", "posted"),
                ("date", ">=", date_start),
                ("date", "<=", date_finish),
            ]
        )
        return moves.mapped("line_ids").filtered(
            lambda line: self._l10n_ec_104_line_has_box(line, box)
        )

    def _l10n_ec_104_line_has_box(self, line, box):
        """Whether the move line carries the ``box`` Reporte 104 tag."""
        for tag in line.tax_tag_ids:
            match = TAG_RE.match(tag.name or "")
            if match and match.group(1) == box:
                return True
        return False

    def _l10n_ec_104_rate_adjustment(
        self, boxes, refund, lower_box, higher_box, variable_boxes=()
    ):
        """Book the rate-difference adjustment for a linked credit note.

        The SRI guide books the absolute tax difference when a credit note
        (returns or discounts) carries a different rate than the original
        document. On the sales side that is 423 (adjustment payable, only
        when the note uses a lower rate *and* the taxpayer files reduced
        variable rates) and 424 (adjustment in favor) otherwise; on the
        purchase side it is 526 (positive credit adjustment, note at a
        lower rate) and 527 (negative) otherwise. The chart ships no
        variable-rate tax, so without variable boxes every sales difference
        lands in 424.

        Lines pair by account and product with the reversed document; the
        compared rates are each line's first ``vat*`` tax (0.0 when the
        line carries no VAT). Multi-rate subtleties beyond one rate per
        side stay out of v1 and are recorded in the roadmap.
        """
        invoice = refund.reversed_entry_id
        invoice_lines = invoice.invoice_line_ids.filtered(
            lambda line: line.display_type == "product"
        )
        for refund_line in refund.invoice_line_ids.filtered(
            lambda line: line.display_type == "product"
        ):
            invoice_line = invoice_lines.filtered(
                lambda line, refund_line=refund_line: (
                    line.account_id == refund_line.account_id
                    and line.product_id == refund_line.product_id
                )
            )[:1]
            rate_invoice = (
                self._l10n_ec_104_vat_rate(invoice_line) if invoice_line else 0.0
            )
            rate_note = self._l10n_ec_104_vat_rate(refund_line)
            if rate_invoice == rate_note:
                continue
            amount = abs(rate_invoice - rate_note) / 100.0 * abs(refund_line.balance)
            if rate_note < rate_invoice and (
                not variable_boxes or any(boxes.get(box) for box in variable_boxes)
            ):
                boxes[lower_box] += amount
            else:
                boxes[higher_box] += amount

    def _l10n_ec_104_vat_rate(self, line):
        """First ``vat*`` tax rate on the line, 0.0 when it carries no VAT."""
        vat_taxes = line.tax_ids.filtered(
            lambda tax: (tax.tax_group_id.l10n_ec_type or "").startswith("vat")
        )
        return vat_taxes[:1].amount if vat_taxes else 0.0
