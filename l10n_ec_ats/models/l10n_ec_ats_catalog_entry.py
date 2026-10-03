from odoo import fields, models


class L10nEcAtsCatalogEntry(models.Model):
    """One row of one SRI referential table, effective-dated.

    Every referential table of the ATS specification is a flat list of codes
    with a validity window, and the applicable version depends on the period
    the ATS is filed for. Odoo 19 cannot express that natively --
    ``account.tax`` has no ``fields.Date`` at all -- so the windows come from
    the :class:`~odoo.addons.l10n_ec_ats.models.l10n_ec_temporal` mixin this
    model inherits.

    One generic model rather than ten typed ones: the catalogs are flat,
    versioned by date and cross-referenced by code, which is exactly a generic
    table with a discriminator. Every entry is a record, so no code path can
    hardcode a rate or a code list.

    The three cross-reference fields are **comma-separated ``Char``** on
    purpose. The mixin resolves entries through an ORM domain, so a
    cross-reference has to stay usable as a domain value; a self-referential
    ``Many2many`` would need load-order gymnastics that the source data does
    not justify, because the SRI states each side of a cross-reference in its
    own column and the two sides do not fully agree.
    """

    _name = "l10n.ec.ats.catalog.entry"
    _inherit = "l10n.ec.temporal"
    _description = "SRI ATS referential catalog entry"
    _order = "table_id, code, date_start, id"

    table_id = fields.Many2one(
        "l10n.ec.ats.catalog.table",
        required=True,
        ondelete="cascade",
        index=True,
        help="The referential table this row belongs to.",
    )
    code = fields.Char(
        required=True,
        index=True,
        help="The SRI code, verbatim, including any trailing zeros. It is not "
        "unique: a code that changes over time has one entry per window.",
    )
    description = fields.Text(
        help="The description as the source cell spells it, stripped of "
        "leading and trailing whitespace only.",
    )
    percentage = fields.Float(
        help="Only ``Tabla 11`` (IVA withholding rates) and ``Tabla 12`` (IVA "
        "rates) carry one.",
    )
    transaction_type_codes = fields.Char(
        help="``Tabla 2`` only: the transaction types of the referred tables "
        "(``A``) this row applies to, comma-separated. Kept as a comma-"
        "separated string rather than a ``Many2many`` because the mixin "
        "resolves a catalog entry through an ORM domain and the cross-"
        "reference has to stay usable as a domain value.",
    )
    document_type_codes = fields.Char(
        help="``Tabla 5`` only: the ``Tabla 4`` document types this tax "
        "support applies to, comma-separated. ``Tabla 4`` only: the "
        "``Tabla 5`` support types that apply to this document type, read "
        "from the SRI's own ``Sustento tributario`` column. Both directions "
        "of the same cross-reference are stored as the source states each "
        "side, because the two columns do not fully agree.",
    )
    sequence_type_codes = fields.Char(
        help="``Tabla 4`` only: the ``Código Secuenciales Transacción`` "
        "values this document type may use, comma-separated. Kept as a "
        "comma-separated string for the same reason as the other "
        "cross-references.",
    )
