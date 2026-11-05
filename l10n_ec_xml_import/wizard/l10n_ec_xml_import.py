"""Wizard: draft vendor bill from an SRI factura XML.

Two doors, one parser (S2): the user attaches the supplier ``factura``
XML, or types its 49-digit access key and the wizard fetches the
authorized XML from the SRI ``autorizacionComprobante`` service and
feeds the same parser. When both arrive, the file wins: it is the
document the supplier actually sent.

Every refusal arrives as one ``UserError``/``ValidationError`` raised in
Python before any SQL: malformed XML, non-``factura`` documents,
missing RUC/clave/lines, reembolsos, mixed VAT rates on one line,
non-IVA-only lines (ICE/IRBPNR need the manual path), unknown VAT
rates, non-dollar currency, bad dates, unknown suppliers that cannot be
created, and bills already imported (same supplier + SRI number, or
same authorization key).

Bills stay DRAFT (Frappe precedent): taxes, sustento and stock behavior
are reviewed before posting.
"""

import base64
import re

from zeep.helpers import serialize_object

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

from ..models.sri_xml import parse_supplier_xml

#: SRI access keys are always 49 digits; anything else is refused as typed.
L10N_EC_XML_ACCESS_KEY_LENGTH = 49


class L10nEcXmlImport(models.TransientModel):
    _name = "l10n.ec.xml.import"
    _description = "Import supplier factura XML"

    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
    )
    journal_id = fields.Many2one(
        "account.journal",
        string="Purchase Journal",
        required=True,
        default=lambda self: self._default_l10n_ec_xml_journal(),
    )
    expense_account_id = fields.Many2one(
        "account.account",
        string="Expense Account",
        required=True,
        default=lambda self: self._default_l10n_ec_xml_expense_account(),
        domain="[('account_type', '=', 'expense')]",
    )
    xml_file = fields.Binary(string="Supplier XML file")
    xml_filename = fields.Char(string="XML filename")
    access_key = fields.Char(string="Access key (clave de acceso)", size=49)

    @api.model
    def _default_l10n_ec_xml_journal(self):
        return self.env["account.journal"].search(
            [
                ("type", "=", "purchase"),
                ("company_id", "=", self.env.company.id),
                ("l10n_ec_is_purchase_liquidation", "=", False),
            ],
            limit=1,
        )

    @api.model
    def _default_l10n_ec_xml_expense_account(self):
        return self.env["account.account"].search(
            [
                ("company_ids", "in", self.env.company.id),
                ("account_type", "=", "expense"),
            ],
            limit=1,
        )

    @api.constrains("access_key")
    def _check_l10n_ec_xml_access_key(self):
        for rec in self:
            if rec.access_key and (
                not rec.access_key.isdigit()
                or len(rec.access_key) != L10N_EC_XML_ACCESS_KEY_LENGTH
            ):
                raise ValidationError(
                    self.env._(
                        "A SRI access key is 49 digits, got '%(key)s'.",
                        key=rec.access_key,
                    )
                )

    def action_import(self):
        """Import the factura and open the draft bill that was created."""
        self.ensure_one()
        response_auth = None
        if self.xml_file:
            xml_text = self._l10n_ec_file_xml()
        elif self.access_key:
            self._check_l10n_ec_xml_key_format(self.access_key)
            xml_text, response_auth = self._l10n_ec_fetch_xml(self.access_key)
        else:
            raise UserError(
                self.env._(
                    "Attach the supplier factura XML or type its 49-digit "
                    "access key. Nothing was imported."
                )
            )
        try:
            parsed = parse_supplier_xml(xml_text)
        except ValueError as exc:
            raise UserError(str(exc)) from exc
        bill = self._l10n_ec_create_bill(parsed, response_auth)
        self._l10n_ec_attach_xml(bill, xml_text, parsed["number"])
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Imported Vendor Bill"),
            "res_model": "account.move",
            "res_id": bill.id,
            "view_mode": "form",
            "target": "current",
        }

    def _l10n_ec_file_xml(self):
        """Decode the attached file; the file wins over the key."""
        self.ensure_one()
        try:
            return base64.b64decode(self.xml_file).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise UserError(
                self.env._(
                    "The attached file is not a readable XML: %(error)s.",
                    error=exc,
                )
            ) from exc

    def _check_l10n_ec_xml_key_format(self, access_key):
        if not access_key.isdigit() or (
            len(access_key) != L10N_EC_XML_ACCESS_KEY_LENGTH
        ):
            raise UserError(
                self.env._(
                    "A SRI access key is 49 digits, got '%(key)s'.",
                    key=access_key,
                )
            )

    # -- SRI fetch ------------------------------------------------------

    def _l10n_ec_fetch_xml(self, access_key):
        """Fetch the authorized XML; return ``(xml, response auth number)``."""
        self.ensure_one()
        response = self._l10n_ec_request_authorization(access_key)
        return self._l10n_ec_extract_authorized_xml(response, access_key)

    def _l10n_ec_get_auth_client(self):
        """Borrow the EDI format's zeep client (cel/celcer URLs)."""
        self.ensure_one()
        environment = self.company_id.l10n_ec_type_environment or "production"
        return self.env["account.edi.format"]._l10n_ec_get_edi_ws_client(
            environment, "authorization"
        )

    def _l10n_ec_request_authorization(self, access_key):
        self.ensure_one()
        client = self._l10n_ec_get_auth_client()
        if not client:
            raise UserError(
                self.env._(
                    "SRI did not answer the authorization query (no client). "
                    "Upload the XML file instead."
                )
            )
        try:
            return client.service.autorizacionComprobante(
                claveAccesoComprobante=access_key
            )
        except Exception as exc:
            raise UserError(
                self.env._(
                    "SRI did not answer the authorization query (%(error)s). "
                    "Upload the XML file instead.",
                    error=exc,
                )
            ) from exc

    def _l10n_ec_extract_authorized_xml(self, response, access_key):
        """Unwrap the authorized ``<comprobante>`` or refuse with its messages."""
        self.ensure_one()
        data = serialize_object(response, dict) or {}
        autorizaciones = (data.get("autorizaciones") or {}).get("autorizacion")
        if not autorizaciones:
            raise UserError(
                self.env._(
                    "SRI has no authorized document for that key "
                    "(not authorized or no longer available). "
                    "Upload the XML file instead."
                )
            )
        if not isinstance(autorizaciones, list):
            autorizaciones = [autorizaciones]
        messages = []
        for doc in autorizaciones:
            for msj in self._l10n_ec_as_list(
                (doc.get("mensajes") or {}).get("mensaje")
            ):
                messages.append(
                    f"{msj.get('tipo') or ''} [{msj.get('identificador') or ''}] "
                    f"{msj.get('mensaje') or ''} "
                    f"{msj.get('informacionAdicional') or ''}"
                )
            if doc.get("estado") != "AUTORIZADO":
                continue
            body = doc.get("comprobante")
            if isinstance(body, str) and body.strip():
                return body.strip(), (doc.get("numeroAutorizacion") or "").strip()
            raise UserError(
                self.env._(
                    "SRI confirmed the authorization but returned no document. "
                    "Upload the XML file instead."
                )
            )
        detail = "; ".join(messages) or self.env._("not authorized")
        raise UserError(
            self.env._(
                "SRI has no authorized document for that key (%(detail)s). "
                "Upload the XML file instead.",
                detail=detail,
            )
        )

    @staticmethod
    def _l10n_ec_as_list(value):
        if not value:
            return []
        return value if isinstance(value, list) else [value]

    # -- bill -----------------------------------------------------------

    def _l10n_ec_create_bill(self, parsed, response_auth=None):
        """Map the parsed factura to a draft ``in_invoice``."""
        self.ensure_one()
        if self.company_id.currency_id.id != self.env.ref("base.USD").id:
            raise UserError(
                self.env._(
                    "Supplier XML amounts are US dollars, but company %(company)s "
                    "uses %(currency)s: review the bill currency before posting.",
                    company=self.company_id.display_name,
                    currency=self.company_id.currency_id.display_name,
                )
            )
        issue_date = self._l10n_ec_issue_date(parsed.get("issue_date"))
        self._l10n_ec_check_currency(parsed.get("currency"))
        line_vals = [
            self._l10n_ec_line_vals(line, position)
            for position, line in enumerate(parsed["lines"], start=1)
        ]
        partner = self._l10n_ec_supplier(
            (parsed.get("emisor_ruc") or "").strip(),
            (parsed.get("emisor_name") or "").strip(),
        )
        auth_number = self._l10n_ec_auth_number(parsed, response_auth)
        self._l10n_ec_refuse_duplicate(partner, parsed["number"], auth_number)
        bill = self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "company_id": self.company_id.id,
                "journal_id": self.journal_id.id,
                "partner_id": partner.id,
                "currency_id": self.company_id.currency_id.id,
                "invoice_date": issue_date,
                "date": issue_date,
                "l10n_latam_document_type_id": self._l10n_ec_document_type().id,
                "l10n_latam_document_number": parsed["number"],
                "ref": parsed["number"],
                "l10n_ec_electronic_authorization": auth_number,
                "invoice_line_ids": [(0, 0, vals) for vals in line_vals],
            }
        )
        return bill

    def _l10n_ec_check_currency(self, moneda):
        cleaned = (moneda or "").strip().upper()
        if cleaned == "DOLAR" or cleaned.startswith("DOLAR "):
            return
        raise UserError(
            self.env._(
                "Supplier XML currency '%(currency)s' is not US dollars "
                "(DOLAR): fix the XML.",
                currency=moneda,
            )
        )

    def _l10n_ec_issue_date(self, sri_date):
        parts = (sri_date or "").strip().split("/")
        if len(parts) != 3 or not all(part.isdigit() for part in parts):
            raise UserError(
                self.env._(
                    "Supplier XML date '%(date)s' is not DD/MM/YYYY.",
                    date=sri_date,
                )
            )
        day, month, year = (int(part) for part in parts)
        if not 1 <= month <= 12 or not 1 <= day <= 31 or year < 2000:
            raise UserError(
                self.env._(
                    "Supplier XML date '%(date)s' is not a real date.",
                    date=sri_date,
                )
            )
        return f"{year:04d}-{month:02d}-{day:02d}"

    def _l10n_ec_auth_number(self, parsed, response_auth=None):
        auth = parsed.get("autorizacion") or {}
        return (
            (response_auth or "").strip()
            or (auth.get("numero_autorizacion") or "").strip()
            or (parsed.get("clave_acceso") or "").strip()
        )

    def _l10n_ec_document_type(self):
        doc_type = self.env.ref("l10n_ec.ec_dt_01", raise_if_not_found=False)
        if not doc_type:
            raise UserError(
                self.env._(
                    "Document type 01 (factura) is not available: "
                    "the Ecuadorian chart must be installed."
                )
            )
        return doc_type

    def _l10n_ec_line_vals(self, line, position):
        iva_taxes = [
            tax for tax in (line.get("taxes") or []) if str(tax.get("code")) == "2"
        ]
        if not (line.get("taxes") or []):
            raise UserError(
                self.env._(
                    "Supplier XML line %(position)s ('%(name)s') "
                    "has no impuestos block.",
                    position=position,
                    name=line.get("description", ""),
                )
            )
        if not iva_taxes:
            raise UserError(
                self.env._(
                    "Supplier XML line %(position)s ('%(name)s') carries no IVA tax: "
                    "ICE/IRBPNR lines need the manual path.",
                    position=position,
                    name=line.get("description", ""),
                )
            )
        rates = {float(tax.get("rate", 0.0)) for tax in iva_taxes}
        if len(rates) != 1:
            raise UserError(
                self.env._(
                    "Supplier XML line %(position)s mixes VAT rates: %(rates)s.",
                    position=position,
                    rates=sorted(rates),
                )
            )
        rate = next(iter(rates))
        rate_code = iva_taxes[0].get("rate_code")
        tax = self._l10n_ec_purchase_tax(rate, rate_code)
        subtotal = float(line.get("qty") or 0) * float(line.get("unit_price") or 0)
        discount_abs = float(line.get("discount") or 0)
        discount_pct = (discount_abs / subtotal * 100.0) if subtotal else 0.0
        return {
            "name": line.get("description")
            or line.get("code")
            or self.env._("Imported SRI line %(position)s", position=position),
            "account_id": self.expense_account_id.id,
            "quantity": float(line.get("qty") or 0),
            "price_unit": float(line.get("unit_price") or 0),
            "discount": discount_pct,
            "tax_ids": [(6, 0, [tax.id])],
        }

    def _l10n_ec_purchase_tax(self, rate, rate_code):
        """Match one purchase tax by exact tarifa, fail loud otherwise.

        The SRI ``codigoPorcentaje`` rides on the tax through
        ``l10n_ec_xml_fe_code`` (2 = 12%, 4 = 15%, 5 = 5%, 8 = 8%, 0 = 0%):
        candidates share company, ``type_tax_use`` and amount. Ties (the
        chart carries one tax per sustento) go to the unqualified
        goods-credit tax ("VAT 15% 510 01"); with no plain candidate
        (0%), the cost-like "02" tax wins, else chart order. The bill
        stays draft, so reclassification is a review step, never
        silent data.
        """
        self.ensure_one()
        candidates = self.env["account.tax"].search(
            [
                ("company_id", "=", self.company_id.id),
                ("type_tax_use", "=", "purchase"),
                ("amount", "=", rate),
                ("l10n_ec_xml_fe_code", "=", rate_code),
            ]
        )
        if not candidates:
            available = ", ".join(
                f"{tax.display_name} ({tax.amount}%)"
                for tax in self.env["account.tax"].search(
                    [
                        ("company_id", "=", self.company_id.id),
                        ("type_tax_use", "=", "purchase"),
                        ("l10n_ec_xml_fe_code", "!=", False),
                    ]
                )
            )
            raise UserError(
                self.env._(
                    "No company purchase tax matches VAT rate '%(rate)s' "
                    "from the supplier XML. Available purchase taxes: %(available)s. "
                    "Create the missing one (same rate, debit-side VAT account) "
                    "or fix the XML.",
                    rate=rate,
                    available=available or self.env._("none configured"),
                )
            )
        preferred = candidates.filtered(
            lambda tax: re.match(r"^VAT [\d.]+% \d+ \d+$", tax.name or "")
        )
        if preferred:
            # The unqualified goods-credit tax ("VAT 15% 510 01").
            candidates = preferred
        else:
            cost_like = candidates.filtered(lambda tax: " 02" in (tax.name or ""))
            if cost_like:
                # Cost/expense sustento default ("VAT 0% 517 02 IR C").
                candidates = cost_like
        return candidates.sorted(key=lambda tax: (tax.sequence, tax.id))[0]

    def _l10n_ec_supplier(self, ruc, name):
        """Resolve the emisor by RUC, creating it on first sight."""
        self.ensure_one()
        partner = self.env["res.partner"].search([("vat", "=", ruc)], limit=1)
        if partner:
            return partner
        if not name:
            raise UserError(
                self.env._(
                    "Supplier XML carries RUC '%(ruc)s' with no name: "
                    "create the supplier manually.",
                    ruc=ruc,
                )
            )
        clash = self.env["res.partner"].search(
            [("name", "=", name), ("vat", "!=", ruc)], limit=1
        )
        if clash:
            raise UserError(
                self.env._(
                    "Supplier name '%(name)s' already exists with a different "
                    "RUC (%(vat)s): resolve it manually.",
                    name=name,
                    vat=clash.vat,
                )
            )
        partner = self.env["res.partner"].create(
            {
                "name": name,
                "vat": ruc,
                "country_id": self.env.ref("base.ec").id,
                "l10n_latam_identification_type_id": self.env.ref("l10n_ec.ec_ruc").id,
                "supplier_rank": 1,
                "category_id": [
                    (
                        4,
                        self.env.ref(
                            "l10n_ec_xml_import.category_imported_supplier"
                        ).id,
                    )
                ],
            }
        )
        partner.message_post(
            body=self.env._(
                "Supplier '%(name)s' (%(ruc)s) was created by the SRI XML import: "
                "please review its master data.",
                name=name,
                ruc=ruc,
            )
        )
        return partner

    def _l10n_ec_refuse_duplicate(self, partner, number, auth_number):
        bill = self.env["account.move"].search(
            [
                ("move_type", "=", "in_invoice"),
                ("company_id", "=", self.company_id.id),
                ("partner_id", "=", partner.id),
                ("ref", "=", number),
            ],
            limit=1,
        )
        if bill:
            raise UserError(
                self.env._(
                    "Supplier invoice '%(number)s' was already imported as %(bill)s.",
                    number=number,
                    bill=bill.display_name,
                )
            )
        if auth_number:
            keyed = self.env["account.move"].search(
                [
                    ("move_type", "=", "in_invoice"),
                    ("company_id", "=", self.company_id.id),
                    ("l10n_ec_electronic_authorization", "=", auth_number),
                ],
                limit=1,
            )
            if keyed:
                raise UserError(
                    self.env._(
                        "Access key '%(key)s' was already imported as %(bill)s.",
                        key=auth_number,
                        bill=keyed.display_name,
                    )
                )

    def _l10n_ec_attach_xml(self, bill, xml_text, number):
        self.ensure_one()
        self.env["ir.attachment"].create(
            {
                "name": self.xml_filename or f"{number}.xml",
                "raw": xml_text.encode("utf-8"),
                "mimetype": "application/xml",
                "res_model": "account.move",
                "res_id": bill.id,
            }
        )
