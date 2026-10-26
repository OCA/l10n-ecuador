from odoo import fields, models


class L10nEcAtsCatalogTable(models.Model):
    """Registry of the SRI referential tables an ATS is built from.

    One record per table of ``Catalogo_ATS.xls``. The registry exists so that
    the catalog layer is inspectable and so that a truncated import is
    detectable: :attr:`entry_count` is the **coverage manifest**, the number
    of rows the source spreadsheet holds for that table, and the T1 test
    asserts the loaded entries match it. Without that number a lost record
    would silently become a coverage hole that only shows up as a rejected
    filing.
    """

    _name = "l10n.ec.ats.catalog.table"
    _description = "SRI ATS referential catalog table"
    _order = "code"

    code = fields.Char(
        required=True,
        index=True,
        help="The SRI table number as a zero-padded string, so it reads and "
        "sorts like the ficha técnica: ``01``, ``02``, ``05``. The "
        "transaction-type catalog of the referred tables carries ``A``.",
    )
    name = fields.Char(
        required=True,
        help="The table's title, spelled as the source spells it.",
    )
    source_reference = fields.Char(
        required=True,
        help="Where the data was read from, including the sheet and the row "
        "range. Traceability is the point: a catalog value nobody can trace "
        "back to a cell cannot be trusted.",
    )
    in_scope = fields.Boolean(
        required=True,
        default=True,
        help="Whether an in-scope ATS block needs this table. False for "
        "anything loaded speculatively.",
    )
    entry_count = fields.Integer(
        required=True,
        help="Coverage manifest: how many entries the source spreadsheet has "
        "for this table. A test asserts the loaded catalog matches, which is "
        "what catches a truncated import.",
    )
    load_order = fields.Integer(
        help="Sequence for deterministic loading. The tables cross-reference "
        "each other, so the order is not free.",
    )
