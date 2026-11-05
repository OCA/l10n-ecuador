"""Generation wizard: the one seam a user can reach.

``l10n.ec.103.generate`` takes a company, a year and a month, and pre-fills
the boxes of that month's withholding return (Formulario 103) that derive
from the posted moves of that month: the resident block, the non-resident
block and the totals. The prefill is offered as a concepto→valor CSV
download (the pair shape the SRI XML/JSON upload guide asks for) and as an
on-screen preview; the filing itself happens in the SRI portal, where the
suggested and manual boxes stay editable.

The period is a field, not a shell argument: ``anio`` refuses a year before
2000 (the SRI only serves periods from 2000 on) so an impossible period is
refused as you type rather than after a full collection pass.

Everything wrong with a period arrives in **one** ``UserError``, numbered,
and no file is produced. A prefill that quietly omits the boxes it could not
compute is the failure this addon exists to prevent. The 500 compensation
is case-file state no move can supply: it travels in ``carryover_500``
defaulting to zero, reported as carried, never as computed.
"""

import calendar
import csv
import io

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

L10N_EC_103_PERIOD_YEAR_FLOOR = 2000


class L10nEc103Generate(models.TransientModel):
    _name = "l10n.ec.103.generate"
    _description = "Ecuadorian Form 103 (withholding) prefill wizard"

    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
    )
    anio = fields.Integer(required=True)
    mes = fields.Integer(required=True)
    carryover_500 = fields.Float(
        string="Box 500: undistributed-profit advance compensation"
    )
    boxes_preview = fields.Text(readonly=True)

    @api.constrains("anio")
    def _check_l10n_ec_103_anio(self):
        for rec in self:
            if rec.anio < L10N_EC_103_PERIOD_YEAR_FLOOR:
                raise ValidationError(
                    self.env._(
                        "The reported year must be %(floor)s or later, got %(anio)s.",
                        floor=L10N_EC_103_PERIOD_YEAR_FLOOR,
                        anio=rec.anio,
                    )
                )

    @api.constrains("mes")
    def _check_l10n_ec_103_mes(self):
        for rec in self:
            if not 1 <= rec.mes <= 12:
                raise ValidationError(
                    self.env._(
                        "The reported month must be between 1 and 12, got %(mes)s.",
                        mes=rec.mes,
                    )
                )

    def _l10n_ec_103_period(self):
        """``(date_start, date_finish)`` for the reported month."""
        self.ensure_one()
        last_day = calendar.monthrange(self.anio, self.mes)[1]
        return (
            fields.Date.to_date(f"{self.anio:04d}-{self.mes:02d}-01"),
            fields.Date.to_date(f"{self.anio:04d}-{self.mes:02d}-{last_day:02d}"),
        )

    def _l10n_ec_103_run(self):
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
                    "(country %(country)s): Form 103 is the Ecuadorian "
                    "SRI return.",
                    company=self.company_id.display_name,
                    country=self.company_id.country_id.code or "unset",
                )
            )
        if problems:
            raise UserError(
                self.env._(
                    "Form 103 prefill refused:\n%(problems)s\n"
                    "Nothing was computed and nothing was assumed.",
                    problems="\n".join(problems),
                )
            )
        date_start, date_finish = self._l10n_ec_103_period()
        collector = self.env["l10n.ec.103.collector"]
        residentes = collector._l10n_ec_103_collect_residentes(
            self.company_id, date_start, date_finish
        )
        exterior = collector._l10n_ec_103_collect_exterior(
            self.company_id, date_start, date_finish
        )
        totals = collector._l10n_ec_103_collect_totals(
            self.company_id,
            residentes,
            exterior,
            carryover={"500": self.carryover_500},
        )
        boxes = {**residentes, **exterior, **totals}
        self.boxes_preview = "\n".join(
            f"{box}: {amount}" for box, amount in sorted(boxes.items())
        )
        return self._l10n_ec_103_attachment(boxes), boxes

    def _l10n_ec_103_attachment(self, boxes):
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
                "name": f"formulario_103_{self.anio:04d}{self.mes:02d}.csv",
                "raw": buffer.getvalue().encode("utf-8"),
                "mimetype": "text/csv",
                "res_model": self._name,
                "res_id": self.id,
            }
        )

    def generate(self):
        """Prefill the 103 boxes, record the preview, offer the download."""
        attachment, _boxes = self._l10n_ec_103_run()
        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{attachment.id}?download=true",
            "target": "self",
        }
