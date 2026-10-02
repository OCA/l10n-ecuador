from odoo import api, fields, models
from odoo.exceptions import ValidationError


class L10nEcAtsIncomeWithholdingRate(models.Model):
    """One concept as the SRI described it, withheld at one rate, in one era.

    This is the dated half of ``Tabla 3.10``, and it carries **everything the
    SRI says about a concept within a window**, not just the rate. The SRI
    republishes the whole concept list every time a regime changes, and it
    reuses codes: the same ``codRetAir`` means *Otras retenciones aplicables
    el 2%* in 2012 and *Impuesto único a la exportación de banano* in 2019.
    One row, one era, one description -- nothing merged, nothing borrowed
    from a neighbouring era.

    That is also why the window comes from the
    :class:`~odoo.addons.l10n_ec_ats.models.l10n_ec_temporal` mixin and why
    ``_applicable_on`` is the only correct way to read one: the ATS is filed
    per month, and the description, the family and the rate that apply all
    depend on that month.

    **The source states a percentage far less often than it states a rate
    cell.** Most cells of the table hold a range, a legal reference or a
    dash. Those are imported as ``unresolved`` with the cell text kept
    verbatim in ``source_note``, never resolved into a number: guessing would
    produce a catalog that looks plausible and is silently wrong, and the
    completeness check refuses a period that needs one instead.
    """

    _name = "l10n.ec.ats.income.withholding.rate"
    _inherit = "l10n.ec.temporal"
    _description = "SRI ATS Tabla 3.10 income withholding rate"
    _order = "concept_id, date_start, id"

    concept_id = fields.Many2one(
        "l10n.ec.ats.income.withholding.concept",
        required=True,
        ondelete="cascade",
        index=True,
        help="The concept code this rate applies to. The code itself is "
        "timeless and carries no description; the window below is what dates "
        "this row, along with the description and family of that era.",
    )
    description = fields.Text(
        required=True,
        help="What the SRI called this concept **in this era**, as the source "
        "cell spells it, stripped of leading and trailing whitespace only. "
        "It is era-scoped because the SRI reuses a code for a different "
        "concept: 341 is *Otras retenciones aplicables el 2%* in 2014 and "
        "*Impuesto único a la exportación de banano* in 2019.",
    )
    family = fields.Selection(
        selection=[
            ("residente", "Pago a residente"),
            ("no_residente", "Pago a no residente"),
        ],
        help="Which side of the ATS ``Tabla 15`` payment type this era places "
        "the concept on: ``01`` is *pago a residente / establecimiento "
        "permanente* and ``02`` is *pago a no residente*. The sheet states "
        "it as the section header the row sits under -- ``CÓDIGOS PARA PAGO "
        "A RESIDENTE``, ``CÓDIGOS PARA PAGO LOCAL``, ``CÓDIGOS PARA PAGOS A "
        "NO RESIDENTE`` or ``CÓDIGOS PARA PAGOS AL EXTERIOR``.\n\n"
        "**Empty where the era states no family at all**, which is the case "
        "for the three oldest era blocks (they have no ``Módulo`` column) and "
        "for the rows above their block's only header. Those rows are left "
        "empty rather than filled from a neighbouring era: no era's value "
        "belongs to another era's row.",
    )
    percentage = fields.Float(
        digits=(5, 2),
        help="The withholding percentage for this window, as the source "
        "states it. ``Float``, not ``Integer``: the SRI publishes fractional "
        "rates such as 1.75, and an integer field would round them to a "
        "different number. Empty when the source cell does not state a single "
        "percentage -- see ``unresolved``.",
    )
    unresolved = fields.Boolean(
        required=True,
        default=False,
        help="The source cell does not state a single percentage, so "
        "``percentage`` is empty and ``source_note`` holds the cell verbatim: "
        "a range, a dash, a legal reference, or a cell naming a resolution "
        "for the real value. The completeness check refuses to generate a "
        "period that needs one, which is the point -- an invented rate would "
        "be indistinguishable from a real one in the filed ATS.",
    )
    source_note = fields.Char(
        help="The source cell verbatim, for a rate the sheet does not state "
        "as a single number. Empty when the cell was a number.",
    )

    @api.constrains("percentage", "unresolved")
    def _check_percentage_matches_unresolved(self):
        """Reject a rate whose flag and value disagree.

        ``fields.Float`` reads a NULL column back as ``0.0``
        (``Float.convert_to_record`` returns ``value or 0.0``), and ``0`` is
        a real published rate -- ``323E2`` is an exempt concept at 0. So the
        ORM alone cannot tell "no value" from "the value zero", and the
        difference is exactly what this invariant is about: a rate of ``0``
        may be filed, a rate with no value may not. The stored column is
        therefore read directly, once for the whole recordset, after an
        explicit flush so the pending write is visible.
        """
        stored = self._stored_percentages()
        for rate in self:
            value = stored.get(rate.id) if rate.id else rate.percentage or None
            if rate.unresolved and value is not None:
                raise ValidationError(
                    self.env._(
                        "The rate of concept %(code)s from %(start)s is marked "
                        "unresolved, so it must carry no percentage. Found "
                        "%(value)s.",
                        code=rate.concept_id.code,
                        start=fields.Date.to_string(rate.date_start),
                        value=value,
                    )
                )
            if not rate.unresolved and value is None:
                raise ValidationError(
                    self.env._(
                        "The rate of concept %(code)s from %(start)s claims a "
                        "resolved percentage but stores none. Fill it in from "
                        "the source, or mark the rate unresolved.",
                        code=rate.concept_id.code,
                        start=fields.Date.to_string(rate.date_start),
                    )
                )

    def _stored_percentages(self):
        """Return ``{rate id: stored percentage or None}`` for ``self``.

        One query for the whole recordset, and an empty mapping for records
        that have no id yet, which is what a ``new()`` record looks like.
        """
        rates = self.filtered("id")
        if not rates:
            return {}
        self.flush_recordset(["percentage"])
        self.env.cr.execute(
            f"SELECT id, percentage FROM {self._table} WHERE id IN %s",
            [tuple(rates.ids)],
        )
        return {row[0]: row[1] for row in self.env.cr.fetchall()}
