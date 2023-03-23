import logging
from os import path

from odoo import models

_logger = logging.getLogger(__name__)
EDI_DATE_FORMAT = "%d/%m/%Y"


class AccountEdiDocument(models.Model):
    _inherit = "account.edi.document"

    def _l10n_ec_get_xsd_filename(self):
        if self.move_id.is_purchase_withhold():
            base_path = path.join("l10n_ec_account_edi", "data", "xsd")
            filename = "ComprobanteRetencion_V2.0.0"
            return path.join(base_path, f"{filename}.xsd")
        return super()._l10n_ec_get_xsd_filename()

    def _l10n_ec_render_xml_edi(self):
        if self.move_id.is_purchase_withhold():
            ViewModel = self.env["ir.ui.view"].sudo()
            return ViewModel._render_template(
                "l10n_ec_withhold.ec_edi_withhold", self._l10n_ec_get_info_withhold()
            )
        return super()._l10n_ec_render_xml_edi()

    def _l10n_ec_get_edi_number(self):
        edi_number = super()._l10n_ec_get_edi_number()
        # withholding save number in field 'ref'
        document = self.l10n_ec_get_current_document()
        if document.is_purchase_withhold():
            edi_number = document.ref
        return edi_number

    def _l10n_ec_get_info_withhold(self):
        self.ensure_one()
        withhold = self.move_id
        type_id = withhold.l10n_ec_get_identification_type()
        withhold_date = self._l10n_ec_get_edi_date()
        company = withhold.company_id or self.env.company
        withhold_data = {
            "fechaEmision": withhold_date.strftime(EDI_DATE_FORMAT),
            "dirEstablecimiento": self._l10n_ec_clean_str(
                withhold.journal_id.l10n_ec_emission_address_id.street or ""
            )[:300],
            "contribuyenteEspecial": company.l10n_ec_get_resolution_data(withhold_date),
            "obligadoContabilidad": self._l10n_ec_get_required_accounting(
                company.partner_id.property_account_position_id
            ),
            "tipoIdentificacionSujetoRetenido": type_id,
            "tipoSujetoRetenido": self._l10n_ec_get_type_suject_withholding(type_id),
            "parteRel": "NO",
            "razonSocialSujetoRetenido": self._l10n_ec_clean_str(
                withhold.commercial_partner_id.name
            )[:300],
            "idSujetoRetenido": withhold.commercial_partner_id.vat,
            "periodoFiscal": withhold_date.strftime("%m/%Y"),
            "docsSustento": self._l10n_ec_get_support_data(),
            "infoAdicional": self._l10n_ec_get_info_additional(),
        }
        withhold_data.update(self._l10n_ec_get_info_tributaria(withhold))
        return withhold_data

    def _l10n_ec_get_type_suject_withholding(self, type_id):
        # codigos son tomados de la ficha técnica ATS, TABLA 14
        type_suject_withholding = False
        if type_id == "08":  # Si tipo identificación es del exterior
            type_suject_withholding = (
                "01"  # Persona Natural TODO: obtener si es compañia "02"
            )
        return type_suject_withholding

    def _l10n_ec_get_withhold_taxes_vals(self, withhold_lines):
        withhold_tax_vals = []
        for withhold_line in withhold_lines:
            for tax in withhold_line.tax_ids:
                rate = tax.amount
                tax_code = tax.l10n_ec_xml_fe_code
                # profit withhold take from l10n_ec_code_base
                if tax.tax_group_id.l10n_ec_type == "withhold_income_purchase":
                    tax_code = tax.l10n_ec_code_base
                tax_vals = {
                    "codigo": tax.tax_group_id.l10n_ec_xml_fe_code,
                    "codigoPorcentaje": tax_code,
                    "baseImponible": self._l10n_ec_number_format(
                        abs(withhold_line.price_unit), 6
                    ),
                    "tarifa": self._l10n_ec_number_format(abs(rate), 6),
                    "valor": self._l10n_ec_number_format(
                        abs(withhold_line.l10n_ec_withhold_tax_amount), 6
                    ),
                }
                withhold_tax_vals.append(tax_vals)
        return withhold_tax_vals

    def _l10n_ec_get_support_data(self):
        def filter_support_invoice_lines(invoice_line):
            invoice_line_tax_support = (
                invoice_line.l10n_ec_tax_support
                or invoice_line.move_id.l10n_ec_tax_support
            )
            return tax_support == invoice_line_tax_support

        docs_sustento = []
        withhold = self.move_id
        # agrupar los documentos por sustento tributario y factura
        invoice_line_data = {}
        for withhold_line in withhold.l10n_ec_withhold_line_ids:
            invoice = withhold_line.l10n_ec_invoice_withhold_id
            line_key = (invoice, withhold_line.l10n_ec_tax_support)
            invoice_line_data.setdefault(line_key, []).append(withhold_line)
        for line_key in invoice_line_data:
            invoice, tax_support = line_key
            withhold_lines = invoice_line_data[line_key]
            invoice_taxes_data = invoice._prepare_edi_tax_details(
                filter_invl_to_apply=filter_support_invoice_lines,
            )
            amount_total = abs(invoice_taxes_data.get("base_amount"))
            date_invoice = invoice._l10n_ec_get_document_date()
            support_data = {
                "codSustento": tax_support,
                "codDocSustento": invoice.l10n_latam_document_type_id.code or "01",
                "numDocSustento": invoice.l10n_latam_document_number.replace("-", ""),
                "fechaEmisionDocSustento": date_invoice.strftime(EDI_DATE_FORMAT),
                "pagoLocExt": "01",  # TODO
                "tipoRegi": False,  # TODO
                "paisEfecPago": False,  # TODO
                "DobTrib": "NO",  # TODO
                "SujRetNorLeg": False,  # TODO
                "pagoRegFis": False,  # TODO
                "totalSinImpuestos": self._l10n_ec_number_format(
                    invoice_taxes_data.get("base_amount"), 6
                ),
                "importeTotal": self._l10n_ec_number_format(amount_total, 6),
                "impuestosDocSustento": self.l10n_ec_header_get_total_with_taxes(
                    invoice_taxes_data
                ),
                "retenciones": self._l10n_ec_get_withhold_taxes_vals(withhold_lines),
                "pagos": [
                    {
                        "name": invoice.l10n_ec_sri_payment_id.name,
                        "formaPago": invoice.l10n_ec_sri_payment_id.code,
                        "total": self._l10n_ec_number_format(amount_total, 6),
                    }
                ],
            }
            docs_sustento.append(support_data)
        return docs_sustento
