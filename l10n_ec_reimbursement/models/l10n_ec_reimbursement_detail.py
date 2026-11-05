"""One reimbursed voucher leg, mirrored from Frappe's SRI Reimbursement Detail.

Each row describes a third-party voucher the intermediary paid and
re-invoices: its SRI document code (Tabla 4), the original supplier's
identification (Tabla 10), its ``001-001-000000001`` number, emission date,
authorization, and the amount buckets the ATS ``reembolsoType`` and the EDI
``reembolsoDetalle`` both read from.
"""

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class L10nEcReimbursementDetail(models.Model):
    _name = "l10n.ec.reimbursement.detail"
    _description = "SRI reimbursed voucher leg"
    _order = "id"

    move_id = fields.Many2one(
        comodel_name="account.move",
        string="Move",
        required=True,
        ondelete="cascade",
        index=True,
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        related="move_id.currency_id",
        readonly=True,
    )
    doc_code = fields.Char(
        string="Doc. Code",
        required=True,
        help="SRI Tabla 4 code of the reimbursed voucher (e.g. 01, 03). "
        "One emission carries a single code.",
    )
    supplier_id_type = fields.Char(
        string="Supplier ID Type",
        required=True,
        help="SRI Tabla 10 identification type of the original supplier (e.g. 04 RUC).",
    )
    supplier_id = fields.Char(
        string="Supplier Tax ID",
        required=True,
        help="Tax ID of the original supplier on the reimbursed voucher.",
    )
    sri_number = fields.Char(
        string="Supplier Voucher Number",
        required=True,
        help="SRI number of the reimbursed voucher (001-001-000000001).",
    )
    issue_date = fields.Date(
        required=True,
        help="Issue date of the reimbursed voucher.",
    )
    auth_number = fields.Char(
        required=True,
        help="SRI authorization number of the reimbursed voucher.",
    )
    base_amount = fields.Monetary(
        currency_field="currency_id",
        required=True,
        help="Base of the reimbursed voucher; sums into totbasesImpReemb.",
    )
    taxed_base = fields.Monetary(
        currency_field="currency_id",
        help="Gravada base of the reimbursed voucher (baseImpGravReemb).",
    )
    no_tax_base = fields.Monetary(
        currency_field="currency_id",
        help="No-object base of the reimbursed voucher (baseNoGraIvaReemb).",
    )
    exempt_base = fields.Monetary(
        currency_field="currency_id",
        help="Exempt base of the reimbursed voucher (baseImpExeReemb).",
    )
    ice_amount = fields.Monetary(
        currency_field="currency_id",
        help="ICE of the reimbursed voucher (montoIceRemb).",
    )
    iva_amount = fields.Monetary(
        currency_field="currency_id",
        help="IVA of the reimbursed voucher (montoIvaRemb).",
    )

    #: Fields the SRI needs on every leg. Missing values refuse in Python
    #: (``create``/``write`` below) instead of at the database: a raw null
    #: violation logs an ERROR line and trips the OCA checklog gate, while a
    #: ``ValidationError`` fails only the offending write.
    _l10n_ec_required_fields = (
        "move_id",
        "doc_code",
        "supplier_id_type",
        "supplier_id",
        "sri_number",
        "issue_date",
        "auth_number",
        "base_amount",
    )

    @api.model_create_multi
    def create(self, vals_list):
        """Refuse legs missing SRI-required values before the INSERT."""
        for vals in vals_list:
            missing = [
                field
                for field in self._l10n_ec_required_fields
                if vals.get(field) is None
                or vals.get(field) is False
                or vals.get(field) == ""
            ]
            if missing:
                raise ValidationError(
                    self.env._(
                        "Reimbursement entry needs %(fields)s.",
                        fields=", ".join(sorted(missing)),
                    )
                )
        return super().create(vals_list)

    def write(self, vals):
        """Refuse blanking SRI-required values after the fact."""
        nulled = [
            field
            for field in self._l10n_ec_required_fields
            if field in vals
            and (vals[field] is None or vals[field] is False or vals[field] == "")
        ]
        if nulled:
            raise ValidationError(
                self.env._(
                    "Reimbursement entry needs %(fields)s.",
                    fields=", ".join(sorted(nulled)),
                )
            )
        return super().write(vals)

    @api.constrains("doc_code", "move_id")
    def _check_single_doc_code(self):
        """Refuse a move mixing reimbursed document codes.

        One emission carries a single ``codDocReembolso``: the totals block
        names exactly one code, so a move holding 01 and 03 legs at once could
        never be emitted honestly. The Frappe side enforces the same rule.
        """
        for detail in self:
            codes = set(detail.move_id.reimbursement_ids.mapped("doc_code"))
            codes.discard(False)
            codes.discard("")
            if len(codes) > 1:
                raise ValidationError(
                    self.env._(
                        "Reimbursed vouchers on %(move)s mix document codes "
                        "%(codes)s. One emission carries a single SRI code, "
                        "so split the vouchers or fix the code.",
                        move=detail.move_id.display_name,
                        codes=", ".join(sorted(codes)),
                    )
                )

    @api.constrains("base_amount", "taxed_base", "no_tax_base", "exempt_base")
    def _check_positive_base(self):
        """Refuse a leg with no base at all.

        Amounts are what both consumers read -- the ATS total and the EDI
        ``detalleImpuestos`` -- so a leg carrying only taxes (or nothing)
        describes a voucher that cannot be reported.
        """
        for detail in self:
            bases = (
                detail.base_amount,
                detail.taxed_base,
                detail.no_tax_base,
                detail.exempt_base,
            )
            if not any(amount > 0 for amount in bases):
                raise ValidationError(
                    self.env._(
                        "Reimbursement entry on %(move)s needs at least one "
                        "base amount above zero (base, taxed, no-tax or "
                        "exempt).",
                        move=detail.move_id.display_name,
                    )
                )

    def _l10n_ec_split_sri_number(self):
        """Split the ``001-001-000000001`` number into its three halves.

        :raises ValidationError: when the stored number is not shaped like one,
            because emitting a guessed establishment or sequential would file a
            voucher the SRI cannot match.
        """
        self.ensure_one()
        parts = (self.sri_number or "").strip().split("-")
        if (
            len(parts) != 3
            or [len(part) for part in parts] != [3, 3, 9]
            or not all(part.isdigit() for part in parts)
        ):
            raise ValidationError(
                self.env._(
                    "Reimbursement entry on %(move)s has no SRI number "
                    "'001-001-000000001' (got '%(number)s').",
                    move=self.move_id.display_name,
                    number=self.sri_number,
                )
            )
        return parts[0], parts[1], parts[2]
