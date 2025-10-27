from odoo import models


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    def l10n_ec_get_invoice_edi_data(self, taxes_data):
        self.ensure_one()
        EdiDocument = self.env["account.edi.document"]
        edi_values = self._prepare_edi_vals_to_export()
        res = {
            "codigoPrincipal": EdiDocument._l10n_ec_clean_str(
                self.product_id.default_code or "NA"
            )[:25],
            "codigoAuxiliar": False,
            "descripcion": EdiDocument._l10n_ec_clean_str(
                (self.product_id.name or self.name or "NA")[:300]
            ),
            "unidadMedida": EdiDocument._l10n_ec_clean_str(
                (self.product_uom_id.display_name or "NA")[:50]
            ),
            "cantidad": EdiDocument._l10n_ec_number_format(self.quantity, decimals=6),
            "precioUnitario": EdiDocument._l10n_ec_number_format(
                self.price_unit, decimals=6
            ),
            "descuento": EdiDocument._l10n_ec_number_format(
                edi_values["price_discount"], decimals=6
            ),
            "precioTotalSinImpuesto": EdiDocument._l10n_ec_number_format(
                edi_values["price_subtotal_before_discount"], decimals=6
            ),
            "detallesAdicionales": self._l10n_ec_get_invoice_edi_additional_data(),
            "impuestos": self._l10n_ec_get_invoice_edi_taxes(taxes_data),
        }
        return res

    def l10n_ec_get_credit_note_edi_data(self, taxes_data):
        self.ensure_one()
        EdiDocument = self.env["account.edi.document"]
        edi_values = self._prepare_edi_vals_to_export()
        res = {
            "codigoInterno": EdiDocument._l10n_ec_clean_str(
                self.product_id.default_code or "NA"
            )[:25],
            "codigoAuxiliar": False,
            "descripcion": EdiDocument._l10n_ec_clean_str(
                (self.product_id.name or self.name or "NA")[:300]
            ),
            "cantidad": EdiDocument._l10n_ec_number_format(self.quantity, decimals=6),
            "precioUnitario": EdiDocument._l10n_ec_number_format(
                self.price_unit, decimals=6
            ),
            "descuento": EdiDocument._l10n_ec_number_format(
                edi_values["price_discount"], decimals=6
            ),
            "precioTotalSinImpuesto": EdiDocument._l10n_ec_number_format(
                edi_values["price_subtotal_before_discount"], decimals=6
            ),
            "detallesAdicionales": self._l10n_ec_get_invoice_edi_additional_data(),
            "impuestos": self._l10n_ec_get_credit_note_edi_taxes(taxes_data),
        }
        return res

    def _l10n_ec_get_invoice_edi_additional_data(self):
        res = []
        return res

    def _l10n_ec_get_credit_note_edi_additional_data(self):
        res = []
        return res

    def _l10n_ec_build_taxes(self, taxes_data=None):
        EdiDocument = self.env["account.edi.document"]
        tax_values = []
        if taxes_data is None:
            return tax_values

        for tax_details in taxes_data.get("tax_details", {}).values():
            taxes = tax_details.get("taxes_data") or []
            if taxes:
                tax_values.append(EdiDocument._l10n_ec_prepare_tax_vals_edi(taxes[0]))
        return tax_values

    def _l10n_ec_get_invoice_edi_taxes(self, taxes_data):
        return self._l10n_ec_build_taxes(taxes_data)

    def _l10n_ec_get_credit_note_edi_taxes(self, taxes_data):
        return self._l10n_ec_build_taxes(taxes_data)

    def l10n_ec_get_debit_note_edi_data(self, taxes_data):
        self.ensure_one()
        EdiDocument = self.env["account.edi.document"]
        detail_dict = {
            "descripcion": EdiDocument._l10n_ec_clean_str(
                (self.product_id.name or self.name or "NA")[:300]
            ),
            "precioUnitario": EdiDocument._l10n_ec_number_format(
                self.price_unit, decimals=6
            ),
        }
        return detail_dict
