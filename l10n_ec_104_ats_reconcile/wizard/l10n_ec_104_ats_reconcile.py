"""Reconciliation wizard: the one seam a user can reach.

``l10n.ec.104.ats.reconcile`` takes a company, a year and a month, and
checks the 104 aggregates of that month against the ATS blocks: Σ
``ventasEstab`` vs the 104's 419 (net vs net), Σ ``montoIva`` vs the 104's
429 rebuilt gross (gross vs gross). The verdict lands on screen and in a
CSV download; a drift names its amounts on both sides instead of hiding
them.

The period is a field, not a shell argument: ``anio`` refuses a year before
2000 so an impossible period is refused as you type rather than after two
collection passes.
"""

import calendar
import csv
import io

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

L10N_EC_104_PERIOD_YEAR_FLOOR = 2000


class L10nEc104AtsReconcile(models.TransientModel):
    _name = "l10n.ec.104.ats.reconcile"
    _description = "Ecuadorian Form 104 vs ATS reconciliation"

    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
    )
    anio = fields.Integer(required=True)
    mes = fields.Integer(required=True)
    result_preview = fields.Text(readonly=True)

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

    def generate(self):
        """Reconcile the month, record the verdict, offer the download."""
        self.ensure_one()
        if self.company_id.country_id.code != "EC":
            raise UserError(
                self.env._(
                    "104 vs ATS reconciliation refused: the company "
                    "%(company)s files outside Ecuador (country %(country)s). "
                    "Nothing was reconciled and nothing was assumed.",
                    company=self.company_id.display_name,
                    country=self.company_id.country_id.code or "unset",
                )
            )
        date_start, date_finish = self._l10n_ec_104_period()
        result = self.env["l10n.ec.104.ats.reconciler"].check_period(
            self.company_id, date_start, date_finish
        )
        lines = []
        for check in result["checks"]:
            lines.append(
                f"{check['check']}: ATS {check['ats']} vs "
                f"104 {check['form_104']} (diff {check['diff']}) -- "
                f"{check['verdict']}"
            )
        lines.append("MATCH" if result["match"] else "DRIFT -- review the checks above")
        self.result_preview = "\n".join(lines)
        attachment = self._l10n_ec_104_attachment(result["checks"])
        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{attachment.id}?download=true",
            "target": "self",
        }

    def _l10n_ec_104_attachment(self, checks):
        """Attach the verdict CSV to the wizard record that produced it."""
        self.ensure_one()
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["check", "ats", "form_104", "diff", "verdict"])
        for check in checks:
            writer.writerow(
                [
                    check["check"],
                    check["ats"],
                    check["form_104"],
                    check["diff"],
                    check["verdict"],
                ]
            )
        return self.env["ir.attachment"].create(
            {
                "name": f"conciliacion_104_ats_{self.anio:04d}{self.mes:02d}.csv",
                "raw": buffer.getvalue().encode("utf-8"),
                "mimetype": "text/csv",
                "res_model": self._name,
                "res_id": self.id,
            }
        )
