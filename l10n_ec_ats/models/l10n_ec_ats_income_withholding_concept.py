from odoo import fields, models


class L10nEcAtsIncomeWithholdingConcept(models.Model):
    """A ``Tabla 3.10`` concept code: the registry, and nothing else.

    ``Tabla 3.10`` is the one referential table of the ATS specification that
    is genuinely relational rather than a flat list: the SRI republishes the
    same code for a new regime, and it **reuses codes for different concepts**
    from one era to the next. Code ``341`` is *Otras retenciones aplicables el
    2%* through 2012-2014 and *Impuesto único a la exportación de banano de
    producción propia - componente 2* from 2015; code ``303A`` is *Utilización
    o aprovechamiento de la imagen o renombre* in the 2014-10 era and
    *Servicios profesionales prestados por sociedades residentes* from 2024-03.
    106 of the 414 codes carry a different description in different eras.

    So the description is **not** a property of the code. Holding it here
    would force one era's wording onto every era, which is a fact the source
    does not state. It lives on
    :class:`~odoo.addons.l10n_ec_ats.models.l10n_ec_ats_income_withholding_rate`
    next to the window that dates it, where each era states its own. The same
    goes for ``family``, which the sheet states as a section header covering a
    span of rows within one era block.

    What remains here is the identity: one row per code, so that a rate can
    point at it and so that the code count is assertable against the sheet.

    This model does **not** inherit :class:`~odoo.addons.l10n_ec_ats.models.
    l10n_ec_temporal`. A code has no validity window: it is identified by its
    code and nothing about it is dated, so inheriting the mixin would force a
    second sentinel date onto a record that genuinely needs none.
    """

    _name = "l10n.ec.ats.income.withholding.concept"
    _description = "SRI ATS Tabla 3.10 income withholding concept code"
    _order = "code"

    # The attribute name is kept as ``_code_uniq`` so the generated database
    # constraint keeps the name ``_sql_constraints`` gave it. Renaming the
    # attribute would add a second constraint and orphan the first.
    _code_uniq = models.Constraint(
        "UNIQUE(code)",
        "The Tabla 3.10 code must be unique.",
    )

    code = fields.Char(
        required=True,
        index=True,
        help="The SRI ``Número de campo``, verbatim, alphanumeric suffixes "
        "included: ``303A``, ``323B1`` and ``323E2`` are real codes, not "
        "numbers. It matches ``ats.xsd``'s ``codRetAirType`` -- 3 to 5 "
        "characters of ``[A-Za-z0-9]`` -- so a code outside that shape could "
        "never be emitted in a valid ATS. Everything else the SRI says about "
        "a code is era-scoped and lives on the rate, because the SRI reuses "
        "codes for different concepts across eras.",
    )
