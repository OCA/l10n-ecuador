"""Emit the ``reembolsos`` block and totals on 01 and 03 documents.

The values merge into the ``_l10n_ec_get_info_invoice`` /
``_l10n_ec_get_info_liquidation`` dicts the QWeb templates already render, so
documents without legs keep byte-identical output: the inherit templates only
emit when ``reembolsos`` is non-empty.

Placement follows the SRI XSD sequence, not the template order: the four
totals live **inside** ``infoFactura`` / ``infoLiquidacionCompra`` (between
``totalDescuento`` and ``totalConImpuestos``) while the ``reembolsos`` block
follows ``detalles``. Emitting the block right after the info element would
order ``reembolsos`` before ``detalles`` and fail schema validation.
"""

from odoo import models
from odoo.exceptions import UserError

from odoo.addons.l10n_ec_account_edi.models.account_edi_document import (
    EDI_DATE_FORMAT,
)

#: IVA rate to SRI Tabla 17 percentage code, for ``detalleImpuesto`` rows
#: synthesized from the leg buckets. The rate is derived from the leg's own
#: amounts (``iva_amount / taxed_base``), never assumed: an unrecognized rate
#: refuses the emission instead of filing a code the SRI never published.
IVA_REEMBOLSO_PERCENT_CODES = {
    0.0: "0",
    12.0: "2",
    14.0: "3",
    15.0: "4",
}


class AccountEdiDocument(models.Model):
    _inherit = "account.edi.document"

    def _l10n_ec_get_info_invoice(self):
        values = super()._l10n_ec_get_info_invoice()
        values.update(self._l10n_ec_get_reimbursement_edi_values())
        return values

    def _l10n_ec_get_info_liquidation(self):
        values = super()._l10n_ec_get_info_liquidation()
        values.update(self._l10n_ec_get_reimbursement_edi_values())
        return values

    def _l10n_ec_get_reimbursement_edi_values(self):
        """The ``reembolsos`` payload of the move, or empty defaults.

        Totals mirror the Frappe emission: the voucher count formatted with
        two decimals, the base as the sum of the IVA buckets (taxed, no-tax,
        exempt), and the tax as the sum of the IVA amounts. ICE has no
        tariff-code source on the leg, so a leg carrying ICE refuses the
        emission rather than filing a rate nobody recorded (see ROADMAP).
        """
        self.ensure_one()
        details = self.move_id.reimbursement_ids
        values = {
            "reembolsos": [],
            "codDocReembolso": False,
            "totalComprobantesReembolso": self._l10n_ec_number_format(0.0),
            "totalBaseImponibleReembolso": self._l10n_ec_number_format(0.0),
            "totalImpuestoReembolso": self._l10n_ec_number_format(0.0),
        }
        if not details:
            return values
        codes = set(details.mapped("doc_code"))
        if any(detail.ice_amount for detail in details):
            raise UserError(
                self.env._(
                    "Reimbursed vouchers on %(move)s carry ICE, and v1 has no "
                    "tariff-code source for the ICE detalleImpuesto. Remove "
                    "the ICE amount or wait for tariff-code support.",
                    move=self.move_id.display_name,
                )
            )
        values["reembolsos"] = [
            self._l10n_ec_reimbursement_edi_line(detail, index)
            for index, detail in enumerate(details, start=1)
        ]
        values["codDocReembolso"] = codes.pop()
        values["totalComprobantesReembolso"] = self._l10n_ec_number_format(len(details))
        values["totalBaseImponibleReembolso"] = self._l10n_ec_number_format(
            sum(
                detail.taxed_base + detail.no_tax_base + detail.exempt_base
                for detail in details
            )
        )
        values["totalImpuestoReembolso"] = self._l10n_ec_number_format(
            sum(detail.iva_amount for detail in details)
        )
        return values

    def _l10n_ec_reimbursement_edi_line(self, detail, index):
        """One ``reembolsoDetalle`` payload in XSD field order.

        ``detalleImpuestos`` carries one row per non-zero IVA bucket: the IVA
        row (rate derived from the leg), the no-object row (code ``6``) and
        the exempt row (code ``7``). Zero-bucket rows are omitted, never
        emitted as empty claims.
        """
        establishment, point, sequential = detail._l10n_ec_split_sri_number()
        return {
            "tipoIdentificacionProveedorReembolso": detail.supplier_id_type,
            "identificacionProveedorReembolso": detail.supplier_id,
            "tipoProveedorReembolso": "01",
            "codDocReembolso": detail.doc_code,
            "estabDocReembolso": establishment,
            "ptoEmiDocReembolso": point,
            "secuencialDocReembolso": sequential,
            "fechaEmisionDocReembolso": detail.issue_date.strftime(EDI_DATE_FORMAT),
            "numeroautorizacionDocReemb": detail.auth_number,
            "impuestos": self._l10n_ec_reimbursement_edi_taxes(detail, index),
        }

    def _l10n_ec_reimbursement_edi_taxes(self, detail, index):
        """The ``detalleImpuesto`` rows of one leg.

        :raises UserError: when the derived IVA rate matches no Tabla 17
            code, because filing an invented percentage is worse than
            refusing the emission.
        """
        taxes = []
        if detail.taxed_base or detail.iva_amount:
            if detail.taxed_base:
                rate = round(detail.iva_amount * 100.0 / detail.taxed_base, 2)
            else:
                rate = False
            code = IVA_REEMBOLSO_PERCENT_CODES.get(rate)
            if code is None:
                raise UserError(
                    self.env._(
                        "Reimbursement entry %(index)s on %(move)s derives "
                        "IVA rate %(rate)s, which matches no SRI "
                        "percentage code. Valid rates: %(valid)s.",
                        index=index,
                        move=detail.move_id.display_name,
                        rate=f"{rate:g}%" if rate is not False else "n/a",
                        valid=", ".join(
                            f"{rate:g}%" for rate in sorted(IVA_REEMBOLSO_PERCENT_CODES)
                        ),
                    )
                )
            taxes.append(
                {
                    "codigo": "2",
                    "codigoPorcentaje": code,
                    "tarifa": self._l10n_ec_number_format(rate or 0.0),
                    "baseImponible": self._l10n_ec_number_format(detail.taxed_base),
                    "valor": self._l10n_ec_number_format(detail.iva_amount),
                }
            )
        if detail.no_tax_base:
            taxes.append(
                {
                    "codigo": "2",
                    "codigoPorcentaje": "6",
                    "tarifa": self._l10n_ec_number_format(0.0),
                    "baseImponible": self._l10n_ec_number_format(detail.no_tax_base),
                    "valor": self._l10n_ec_number_format(0.0),
                }
            )
        if detail.exempt_base:
            taxes.append(
                {
                    "codigo": "2",
                    "codigoPorcentaje": "7",
                    "tarifa": self._l10n_ec_number_format(0.0),
                    "baseImponible": self._l10n_ec_number_format(detail.exempt_base),
                    "valor": self._l10n_ec_number_format(0.0),
                }
            )
        return taxes
