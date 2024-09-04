import base64
import re
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_repr
from odoo.tools.misc import remove_accents

from odoo.addons.l10n_ec.models.res_partner import (
    PartnerIdTypeEc,
)
from odoo.addons.l10n_ec_withhold.models.data import TAX_SUPPORT

EDI_DATE_FORMAT = "%d/%m/%Y"
TIPOEMISION = "F"
L10N_EC_VAT_TAX_NOT_ZERO_GROUPS = (
    "vat05",
    "vat08",
    "vat12",
    "vat13",
    "vat14",
    "vat15",
)

L10N_EC_CODE_APPLIED = {
    "valRetBien10": "721",
    "valRetServ20": "723",
    "valorRetBienes": "725",
    "valRetServ50": "727",
    "valorRetServicios": "729",
    "valRetServ100": "731",
}

ATS_SALE_DOCUMENT_TYPE = {
    "01": "18",
    "02": "18",
}


class SriAts(models.Model):
    _name = "sri.ats"

    name = fields.Char(compute="_compute_name", store=True)
    date_start = fields.Date(
        string="Start Date", default=lambda self: self._default_start_date()
    )
    date_end = fields.Date(
        string="End Date", default=lambda self: self._default_end_date()
    )
    xml_file = fields.Binary(string="XML File", readonly=True, store=True)
    file_name = fields.Char(readonly=True, store=True)
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        default=lambda self: self.env.company,
        required=True,
    )
    sri_state = fields.Selection(
        [
            ("draft", "Draft"),
            ("done", "Done"),
        ],
        string="SRI State",
        default="draft",
        required=True,
    )

    @api.model
    def _default_start_date(self):
        today = date.today()
        first_day_last_month = today.replace(day=1) - relativedelta(months=1)
        return first_day_last_month

    @api.model
    def _default_end_date(self):
        today = date.today()
        first_day_this_month = today.replace(day=1)
        last_day_last_month = first_day_this_month - timedelta(days=1)
        return last_day_last_month

    @api.depends("date_start", "date_end")
    def _compute_name(self):
        for record in self:
            if record.date_start and record.date_end:
                record.file_name = "AT%s.xml" % (record.date_end.strftime("%Y%m"))
                record.name = "AT%s" % (record.date_end.strftime("%Y%m"))
            else:
                record.file_name = False
                record.name = False

    def action_draft(self):
        self.write({"sri_state": "draft"})

    def action_done(self):
        self.write({"sri_state": "done"})

    def action_load(self):
        self._validate_ats()
        self.file_name = "%s.xml" % self.name
        xml_file = self._l10n_ec_render_xml_ats()
        self.xml_file = base64.b64encode(xml_file.encode("utf-8"))

    def _get_out_invoice(self):
        return self.env["account.move"].search(
            [
                ("move_type", "in", ["out_invoice", "out_refund"]),
                ("state", "=", "posted"),
                ("invoice_date", ">=", self.date_start),
                ("invoice_date", "<=", self.date_end),
                ("company_id", "=", self.company_id.id),
            ],
            order="partner_id, invoice_date",
        )

    def _get_in_invoice(self):
        return self.env["account.move"].search(
            [
                ("move_type", "in", ["in_invoice", "in_refund"]),
                ("state", "=", "posted"),
                ("invoice_date", ">=", self.date_start),
                ("invoice_date", "<=", self.date_end),
                ("company_id", "=", self.company_id.id),
            ],
            order="partner_id, invoice_date",
        )

    def l10n_ec_tax_support(self, invoice):
        tax_support = invoice.l10n_ec_tax_support
        if not tax_support:
            tax_support = invoice.invoice_line_ids.mapped("l10n_ec_tax_support")
            if tax_support:
                tax_support = tax_support[0]
        if not tax_support:
            tax_support = TAX_SUPPORT[0][0]
        return tax_support

    def l10n_ec_get_withhold_amounts(self, invoice):
        l10n_ec_withhold_ids = invoice.l10n_ec_withhold_ids.filtered(
            lambda x: x.state == "posted"
        )
        l10n_ec_withhold_lines = l10n_ec_withhold_ids.mapped(
            "l10n_ec_withhold_line_ids"
        ).filtered(lambda x: x.l10n_ec_invoice_withhold_id == invoice and x.tax_ids)
        data_withhold = {}

        for line in l10n_ec_withhold_lines:
            code = line.tax_ids[0].l10n_ec_code_applied
            if code not in data_withhold:
                data_withhold[code] = {"balance": 0.0, "amount": 0.0}
            data_withhold[code]["balance"] += line.balance
            data_withhold[code]["amount"] += line.l10n_ec_withhold_tax_amount

        data = {
            "valRetBien10": float_repr(
                data_withhold.get(L10N_EC_CODE_APPLIED["valRetBien10"], {}).get(
                    "amount", 0.0
                ),
                2,
            ),
            "valRetServ20": float_repr(
                data_withhold.get(L10N_EC_CODE_APPLIED["valRetServ20"], {}).get(
                    "amount", 0.0
                ),
                2,
            ),
            "valorRetBienes": float_repr(
                data_withhold.get(L10N_EC_CODE_APPLIED["valorRetBienes"], {}).get(
                    "amount", 0.0
                ),
                2,
            ),
            "valRetServ50": float_repr(
                data_withhold.get(L10N_EC_CODE_APPLIED["valRetServ50"], {}).get(
                    "amount", 0.0
                ),
                2,
            ),
            "valorRetServicios": float_repr(
                data_withhold.get(L10N_EC_CODE_APPLIED["valorRetServicios"], {}).get(
                    "amount", 0.0
                ),
                2,
            ),
            "valRetServ100": float_repr(
                data_withhold.get(L10N_EC_CODE_APPLIED["valRetServ100"], {}).get(
                    "amount", 0.0
                ),
                2,
            ),
        }
        data_air = {}
        withhold_income_purchase_lines = l10n_ec_withhold_lines.filtered(
            lambda x: x.tax_ids[0].tax_group_id.l10n_ec_type
            in ["withhold_income_purchase"]
        )
        if withhold_income_purchase_lines:
            air_vals = []
            for line in withhold_income_purchase_lines:
                tax = line.tax_ids[0]
                air_vals.append(
                    {
                        "codRetAir": tax.l10n_ec_code_ats or "NA",
                        "porcentajeAir": float_repr(abs(tax.amount), 2),
                        "baseImpAir": float_repr(abs(line.balance), 2),
                        "valRetAir": float_repr(
                            abs(line.l10n_ec_withhold_tax_amount), 2
                        ),
                    }
                )
            first_withhold_id = withhold_income_purchase_lines[0].l10n_ec_withhold_id
            EdiDocument = self.env["account.edi.document"]
            (
                entity_number,
                printer_point_number,
                document_number,
            ) = EdiDocument._l10n_ec_split_document_number(
                first_withhold_id.l10n_latam_document_number
            )

            data_air.update(
                {
                    "air": True,
                    "detalleAir": air_vals,
                    "estabRetencion1": entity_number,
                    "ptoEmiRetencion1": printer_point_number,
                    "secRetencion1": document_number,
                    "autRetencion1": first_withhold_id.l10n_ec_xml_access_key or "",
                    "fechaEmiRet1": first_withhold_id.date.strftime(EDI_DATE_FORMAT),
                }
            )
        data.update(data_air)
        return data

    def l10n_ec_get_withhold_amounts_sale(self, invoices):
        l10n_ec_withhold_ids = invoices.l10n_ec_withhold_ids.filtered(
            lambda x: x.state == "posted"
        )
        l10n_ec_withhold_lines = l10n_ec_withhold_ids.mapped(
            "l10n_ec_withhold_line_ids"
        ).filtered(lambda x: x.l10n_ec_invoice_withhold_id == invoices and x.tax_ids)
        data_withhold = {}

        for line in l10n_ec_withhold_lines:
            code = line.tax_ids[0].tax_group_id.l10n_ec_type
            if code not in data_withhold:
                data_withhold[code] = {"balance": 0.0, "amount": 0.0}
            data_withhold[code]["balance"] += line.balance
            data_withhold[code]["amount"] += line.l10n_ec_withhold_tax_amount
        data = {
            "valorRetIva": float_repr(
                data_withhold.get("withhold_vat_sale", {}).get("amount", 0.0), 2
            ),
            "valorRetRenta": float_repr(
                data_withhold.get("withhold_income_sale", {}).get("amount", 0.0), 2
            ),
        }

        return data

    def l10n_ec_get_amounts(self, invoices, type_amounts="in"):
        base_amounts = {}
        for line in invoices.line_ids.filtered(lambda x: x.display_type == "product"):
            key = line.tax_ids.tax_group_id.l10n_ec_type
            if key not in base_amounts:
                base_amounts[key] = {"base": 0.0, "tax": 0.0}
            base_amounts[key]["base"] += abs(line.balance)
            base_amounts[key]["tax"] += abs(line.price_total) - abs(line.price_subtotal)
        montoIce = 0.0  # TODO: Implementar ICE
        totbasesImpReemb = 0.0  # TODO: Implementar Reembolsos en compras
        data = {}
        if type_amounts == "in":
            data = {
                "baseNoGraIva": float_repr(
                    base_amounts.get("not_charged_vat", {}).get("base", 0.0), 2
                ),
                "baseImponible": float_repr(
                    base_amounts.get("zero_vat", {}).get("base", 0.0), 2
                ),
                "baseImpGrav": float_repr(
                    sum(
                        base_amounts.get(ec_type, {}).get("base", 0.0)
                        for ec_type in L10N_EC_VAT_TAX_NOT_ZERO_GROUPS
                    ),
                    2,
                ),
                "baseImpExe": float_repr(
                    base_amounts.get("exempt_vat", {}).get("base", 0.0), 2
                ),
                "montoIva": float_repr(
                    sum(
                        base_amounts.get(ec_type, {}).get("tax", 0.0)
                        for ec_type in L10N_EC_VAT_TAX_NOT_ZERO_GROUPS
                    ),
                    2,
                ),
                "montoIce": float_repr(montoIce, 2),
                "totbasesImpReemb": float_repr(totbasesImpReemb, 2),
            }
        if type_amounts == "out":
            data = {
                "baseNoGraIva": float_repr(
                    base_amounts.get("exempt_vat", {}).get("base", 0.0)
                    + base_amounts.get("not_charged_vat", {}).get("base", 0.0),
                    2,
                ),
                "baseImponible": float_repr(
                    base_amounts.get("zero_vat", {}).get("base", 0.0), 2
                ),
                "baseImpGrav": float_repr(
                    sum(
                        base_amounts.get(ec_type, {}).get("base", 0.0)
                        for ec_type in L10N_EC_VAT_TAX_NOT_ZERO_GROUPS
                    ),
                    2,
                ),
                "montoIva": float_repr(
                    sum(
                        base_amounts.get(ec_type, {}).get("tax", 0.0)
                        for ec_type in L10N_EC_VAT_TAX_NOT_ZERO_GROUPS
                    ),
                    2,
                ),
                "montoIce": float_repr(montoIce, 2),
            }

        return data

    def l10n_ec_get_exterior_payment(self, invoice):
        # TODO: Implementar pago exterior
        return {
            "pagoLocExt": "01",
            "paisEfecPago": "NA",
            "aplicConvDobTrib": "NA",
            "pagExtSujRetNorLeg": "NA",
        }

    def l10n_ec_get_payment(self, invoices):
        payments = []
        for invoice in invoices:
            payments += invoice._l10n_ec_get_payment_data()
        if payments:
            codes = list(set(payment["formaPago"] for payment in payments))
            return {"formaPago": True, "formaPagos": codes}
        return {}

    def _l10n_ec_in_invoice(self):
        purchase_invoices = self._get_in_invoice()
        EdiDocument = self.env["account.edi.document"]
        compras_detalles = []
        for invoice in purchase_invoices:
            partner = invoice.partner_id
            (
                entity_number,
                printer_point_number,
                document_number,
            ) = EdiDocument._l10n_ec_split_document_number(
                invoice.l10n_latam_document_number
            )
            data = {
                "codSustento": self.l10n_ec_tax_support(invoice),
                "tpIdProv": PartnerIdTypeEc.get_ats_code_for_partner(
                    partner, "in_"
                ).value,
                "idProv": partner.vat,
                "tipoComprobante": invoice.l10n_latam_document_type_id.code or "01",
                "parteRel": partner.is_related_partner(),
                "fechaRegistro": invoice.invoice_date.strftime(EDI_DATE_FORMAT),
                "establecimiento": entity_number,
                "puntoEmision": printer_point_number,
                "secuencial": document_number,
                "fechaEmision": invoice.invoice_date.strftime(EDI_DATE_FORMAT),
                "autorizacion": invoice.l10n_ec_electronic_authorization or "",
                "air": {},
            }
            data.update(self.l10n_ec_get_amounts(invoice))
            data.update(self.l10n_ec_get_withhold_amounts(invoice))
            data.update(self.l10n_ec_get_exterior_payment(invoice))
            data.update(self.l10n_ec_get_payment(invoice))
            compras_detalles.append(data)

        return {
            "exist_compras": bool(compras_detalles),
            "compras_detalles": compras_detalles,
        }

    def _l10n_ec_get_establecimiento(self, invoices):
        journal_ids = self._get_estab_ats_ruc()
        venta_est = []
        data_emision = {}
        for journal_id in journal_ids:
            emision = journal_id.l10n_ec_emission
            if emision not in data_emision:
                data_emision[emision] = {"ventasEstab": 0, "ivaComp": 0}
            journal_invoices = invoices.filtered(
                lambda x, j=journal_id: x.journal_id == j
            )
            data_emision[emision]["ventasEstab"] += sum(
                journal_invoices.mapped("amount_untaxed_signed")
            )
            data_emision[emision]["ivaComp"] += sum(
                journal_invoices.mapped("amount_tax")
            )
        for key, value in data_emision.items():
            venta_est.append(
                {
                    "codEstab": key,
                    "ventasEstab": float_repr(value["ventasEstab"], 2),
                    "ivaComp": float_repr(value["ivaComp"], 2),
                }
            )
        return venta_est

    def _l10n_ec_out_invoice(self):
        sale_invoices = self._get_out_invoice()
        totalVentas = float_repr(
            sum(sale_invoices.mapped("amount_untaxed_signed")) or 0.0, 2
        )

        ventas_detalles = []
        partner_ids = sale_invoices.mapped("partner_id")
        for partner_id in partner_ids:
            partner_invoices = sale_invoices.filtered(
                lambda x, p=partner_id: x.partner_id == p
            )
            documents_types = partner_invoices.mapped("l10n_latam_document_type_id")
            for document_type in documents_types:
                invoices = partner_invoices.filtered(
                    lambda x, dt=document_type: x.l10n_latam_document_type_id == dt
                )
                document_code = document_type.code
                tipo_comprobante = (
                    ATS_SALE_DOCUMENT_TYPE.get(document_code) or document_code
                )

                data = {
                    "tpIdCliente": PartnerIdTypeEc.get_ats_code_for_partner(
                        partner_id, "out_"
                    ).value,
                    "idCliente": partner_id.vat,
                    "parteRelVtas": partner_id.is_related_partner(),
                    "tipoComprobante": tipo_comprobante,
                    "tipoEmision": TIPOEMISION,
                    "numeroComprobantes": len(invoices),
                }
                data.update(self.l10n_ec_get_amounts(invoices, "out"))
                data.update(self.l10n_ec_get_payment(invoices))
                data.update(self.l10n_ec_get_withhold_amounts_sale(invoices))
                ventas_detalles.append(data)

        return {
            "exist_ventas": bool(sale_invoices),
            "ventas_detalles": ventas_detalles,
            "totalVentas": totalVentas,
            "venta_est": self._l10n_ec_get_establecimiento(sale_invoices),
        }

    def _get_estab_ats_ruc(self):
        journal_ids = self.env["account.journal"].search(
            [
                ("company_id", "=", self.company_id.id),
                ("type", "=", "sale"),
                ("l10n_latam_use_documents", "=", True),
            ]
        )
        return journal_ids

    def _get_num_estab_ruc(self):
        journal_ids = self._get_estab_ats_ruc()
        num = len(journal_ids.mapped("l10n_ec_emission"))
        return f"{num:03d}"

    def _l10n_ec_get_info_ats(self):
        self.ensure_one()
        company = self.company_id
        social_name = self._l10n_ec_clean_str(company.partner_id.name)
        numEstabRuc = self._get_num_estab_ruc()
        codigoOperativo = "IVA"
        data = {
            "tipoIDInformante": "R",
            "idInformante": company.partner_id.vat,
            "razonSocial": social_name,
            "anio": self.date_end.strftime("%Y"),
            "mes": self.date_end.strftime("%m"),
            "numEstabRuc": numEstabRuc,
            "codigoOperativo": codigoOperativo,
        }
        data.update(self._l10n_ec_in_invoice())
        data.update(self._l10n_ec_out_invoice())
        return data

    def _l10n_ec_render_xml_ats(self):
        ViewModel = self.env["ir.ui.view"].sudo()
        xml_file = ViewModel._render_template(
            "l10n_ec_sri_reports.ec_edi_sri", self._l10n_ec_get_info_ats()
        )
        return xml_file

    def _validate_ats(self):
        if not self.date_start or not self.date_end:
            raise UserError(_("Please set the start and end date"))

    @api.model
    def _l10n_ec_clean_str(self, str_to_clean):
        """
        Clean special characters
        :param str_to_clean: string to clean special characters
        :return str with  special characters removed
        """
        return re.sub("[^-A-Za-z0-9/?:().,'+ ]", "", remove_accents(str_to_clean))
