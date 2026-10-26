# UI label list for the tax support dropdown of the withholding wizard and of
# the invoice lines.
#
# **This is a label list, not the authority.** ``Tabla 5`` is effective-dated
# and holds 16 codes; this literal cannot express a code nobody added to it, and
# it did not: it stopped at ``13`` and silently made the two codes the SRI added
# later -- ``14`` (2018-01-01) and ``15`` (2020-06-01) -- unrecordable. The
# descriptions below are transcribed from ``Catalogo_ATS.xls`` / ``TABLAS
# REFERENCIALES``, the same source ``l10n_ec_ats`` loads as records in
# ``data/ats_catalog_05.xml``, so the wording can be checked without guessing.
#
# The drift risk is real and accepted: nothing keeps this list in step with the
# catalogue, and a code added by a future SRI resolution will not appear here
# until somebody adds it. That is why ``account.move`` and ``res.partner`` store
# the code as a plain ``Char`` and let ``l10n_ec_ats`` validate it against the
# catalogue -- guidance comes from the records, and this list only labels a
# dropdown. See ``l10n_ec_ats/readme/CONFIGURE.md``.
TAX_SUPPORT = [
    ("00", "00 - No aplica"),
    (
        "01",
        "01 - Crédito Tributario para declaración de IVA \
         (servicios y bienes distintos de inventarios y activos fijos)",
    ),
    (
        "02",
        "02 - Costo o Gasto para declaración de IR \
        (servicios y bienes distintos de inventarios y activos fijos)",
    ),
    ("03", "03 - Activo Fijo - Crédito Tributario para declaración de IVA"),
    ("04", "04 - Activo Fijo - Costo o Gasto para declaración de IR"),
    (
        "05",
        "05 - Liquidación Gastos de Viaje, hospedaje y alimentación Gastos IR \
        (a nombre de empleados y no de la empresa)",
    ),
    ("06", "06 - Inventario - Crédito Tributario para declaración de IVA"),
    ("07", "07 - Inventario - Costo o Gasto para declaración de IR"),
    ("08", "08 - Valor pagado para solicitar Reembolso de Gasto (intermediario)"),
    ("09", "09 - Reembolso por Siniestros"),
    ("10", "10 - Distribución de Dividendos, Beneficios o Utilidades"),
    ("11", "11 - Convenios de débito o recaudación para IFI´s"),
    ("12", "12 - Impuestos y retenciones presuntivos"),
    (
        "13",
        "13 - Valores reconocidos por entidades del sector público \
        a favor de sujetos pasivos",
    ),
    (
        "14",
        "14 - Valores facturados por socios a operadoras de transporte \
        (que no constituyen gasto de dicha operadora)",
    ),
    (
        "15",
        "15 - Pagos efectuados por consumos propios y de terceros \
        de servicios digitales",
    ),
]
