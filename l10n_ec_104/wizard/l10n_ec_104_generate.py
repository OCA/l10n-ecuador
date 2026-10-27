"""Generation wizard: the one seam a user can reach.

``l10n.ec.104.generate`` takes a company, a year and a month, and pre-fills
the boxes of that month's Form 104 from its posted moves: the sales block
(401-454), the purchase block (500-560) and the settlement (480-499,
563-565, 601-699, 799-859). The prefill is offered as a CSV download and as
an on-screen preview; the filing itself happens in the SRI portal, where the
suggested boxes (563/564/565, carryovers) stay editable.

The period is a field, not a shell argument: ``anio`` refuses a year before
2000 (the SRI only serves periods from 2000 on) so an impossible period is
refused as you type rather than after a full collection pass.

Everything wrong with a period arrives in **one** ``UserError``, numbered,
and no file is produced. A prefill that quietly omits the boxes it could not
compute is the failure this addon exists to prevent, so the refusal ends by
saying that nothing was computed and nothing was assumed. Cross-period
inputs (prior 485, prior credit balances, compensations) are not derived:
they travel in the ``carryover_*`` fields the user fills from their prior
filing.
"""

import calendar
import csv
import io

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

L10N_EC_104_PERIOD_YEAR_FLOOR = 2000

#: Prior-period and case-file boxes the collector cannot derive, as
#: ``(field_suffix, box, label)``. They default to 0.0 and travel to the
#: settlement as the ``carryover`` dict.
CARRYOVER_BOXES = (
    ("483", "483", "Prior-month tax to settle"),
    ("603", "603", "E-invoicing / senior-citizen offset"),
    ("604", "604", "Solidarity-zone offset"),
    ("605", "605", "Prior credit balance (purchases/imports)"),
    ("606", "606", "Prior credit balance (withholdings received)"),
    ("607", "607", "Prior credit balance (e-invoicing offset)"),
    ("608", "608", "Prior credit balance (solidarity offset)"),
    ("610", "610", "E-invoicing refund adjustment"),
    ("611", "611", "Solidarity-zone refund adjustment"),
    ("612", "612", "Returned/rejected VAT adjustment (credit)"),
    ("613", "613", "Returned/rejected VAT adjustment (withholdings)"),
    ("614", "614", "Public-sector VAT refund adjustment"),
    ("621", "621", "Gambling presumptive / multi-rate sales withholding"),
    ("800", "800", "Provisional VAT refund offset"),
    ("802", "802", "Unpaid withholdings (public sector)"),
)


class L10nEc104Generate(models.TransientModel):
    _name = "l10n.ec.104.generate"
    _description = "Ecuadorian Form 104 (IVA) prefill wizard"

    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
    )
    anio = fields.Integer(required=True)
    mes = fields.Integer(required=True)
    carryover_483 = fields.Float(string="Box 483: prior-month tax to settle")
    carryover_603 = fields.Float(string="Box 603: e-invoicing offset")
    carryover_604 = fields.Float(string="Box 604: solidarity-zone offset")
    carryover_605 = fields.Float(string="Box 605: prior credit (purchases)")
    carryover_606 = fields.Float(string="Box 606: prior credit (withheld)")
    carryover_607 = fields.Float(string="Box 607: prior credit (e-invoicing)")
    carryover_608 = fields.Float(string="Box 608: prior credit (solidarity)")
    carryover_610 = fields.Float(string="Box 610: e-invoicing adjustment")
    carryover_611 = fields.Float(string="Box 611: solidarity adjustment")
    carryover_612 = fields.Float(string="Box 612: returned VAT (credit)")
    carryover_613 = fields.Float(string="Box 613: returned VAT (withheld)")
    carryover_614 = fields.Float(string="Box 614: public-sector refund")
    carryover_621 = fields.Float(string="Box 621: presumptive/miscellaneous")
    carryover_800 = fields.Float(string="Box 800: provisional refund offset")
    carryover_802 = fields.Float(string="Box 802: unpaid (public sector)")
    boxes_preview = fields.Text(readonly=True)

    @api.constrains("anio")
    def _check_l10n_ec_104_anio(self):
        for rec in self:
            if rec.anio < L10N_EC_104_PERIOD_YEAR_FLOOR:
                raise ValidationError(
                    self.env._(
                        "The reported year must be %(floor)s or later, got %(anio)s.",
                        floor=L10N_EC_104_PERIOD_YEAR_FLOOR,
                        anio=rec.anio,
                    )
                )

    @api.constrains("mes")
    def _check_l10n_ec_104_mes(self):
        for rec in self:
            if not 1 <= rec.mes <= 12:
                raise ValidationError(
                    self.env._(
                        "The reported month must be between 1 and 12, got %(mes)s.",
                        mes=rec.mes,
                    )
                )

    def _l10n_ec_104_period(self):
        """``(date_start, date_finish)`` for the reported month."""
        self.ensure_one()
        last_day = calendar.monthrange(self.anio, self.mes)[1]
        return (
            fields.Date.to_date(f"{self.anio:04d}-{self.mes:02d}-01"),
            fields.Date.to_date(f"{self.anio:04d}-{self.mes:02d}-{last_day:02d}"),
        )

    def _l10n_ec_104_carryover(self):
        """User-filled prior-period boxes, as the collector expects them."""
        self.ensure_one()
        return {
            box: self[f"carryover_{box}"]
            for _field_suffix, box, _label in CARRYOVER_BOXES
        }

    def _l10n_ec_104_run(self):
        """Collect the three blocks, refuse problems aggregated, attach CSV.

        :return: ``(attachment, boxes)`` with every prefilled box.
        :raises UserError: with every problem found, not the first; no file
            is produced and nothing is reported as computed.
        """
        self.ensure_one()
        problems = []
        if self.company_id.country_id.code != "EC":
            problems.append(
                self.env._(
                    "1. The company %(company)s files outside Ecuador "
                    "(country %(country)s): Form 104 is the Ecuadorian "
                    "SRI return.",
                    company=self.company_id.display_name,
                    country=self.company_id.country_id.code or "unset",
                )
            )
        if problems:
            raise UserError(
                self.env._(
                    "Form 104 prefill refused:\n%(problems)s\n"
                    "Nothing was computed and nothing was assumed.",
                    problems="\n".join(problems),
                )
            )
        date_start, date_finish = self._l10n_ec_104_period()
        collector = self.env["l10n.ec.104.collector"]
        ventas = collector._l10n_ec_104_collect_ventas(
            self.company_id, date_start, date_finish
        )
        compras = collector._l10n_ec_104_collect_compras(
            self.company_id, date_start, date_finish
        )
        liquidacion = collector._l10n_ec_104_collect_liquidacion(
            self.company_id,
            date_start,
            date_finish,
            ventas,
            compras,
            carryover=self._l10n_ec_104_carryover(),
        )
        boxes = {**ventas, **compras, **liquidacion}
        self.boxes_preview = "\n".join(
            f"{box}: {amount}" for box, amount in sorted(boxes.items())
        )
        return self._l10n_ec_104_attachment(boxes), boxes

    def _l10n_ec_104_attachment(self, boxes):
        """Attach the prefill CSV to the wizard record that produced it.

        Attached rather than handed back inline so the download goes through
        ``/web/content`` with the same access check as any other file, and
        so the bytes a user saves are the bytes that were computed rather
        than a round trip through a browser variable.
        """
        self.ensure_one()
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["casillero", "valor"])
        for box, amount in sorted(boxes.items()):
            writer.writerow([box, amount])
        return self.env["ir.attachment"].create(
            {
                "name": f"formulario_104_{self.anio:04d}{self.mes:02d}.csv",
                "raw": buffer.getvalue().encode("utf-8"),
                "mimetype": "text/csv",
                "res_model": self._name,
                "res_id": self.id,
            }
        )

    def generate(self):
        """Prefill the 104 boxes, record the preview, offer the download."""
        attachment, _boxes = self._l10n_ec_104_run()
        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{attachment.id}?download=true",
            "target": "self",
        }
