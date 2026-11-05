"""Parse SRI supplier ``factura`` XML into plain data (no Odoo dependency).

The parser mirrors ``parse_emitted_xml``/``_parse_factura`` from Frappe
``l10n_ec.sri.voucher_data``: it accepts a bare ``<factura>`` or the
``<autorizacion>`` envelope the SRI returns (``<comprobante>`` carrying
the signed document, usually as CDATA), and returns the number, RUC,
dates, totals and per-line taxes (``codigo``/``codigoPorcentaje``/
``tarifa``/``base``/``valor``) the wizard needs to build a draft bill.

Everything the XML must carry is required fail-loud with an English
message; nothing is guessed. The caller (wizard) turns ``ValueError``
into ``UserError`` so refusals stay in Python, before any SQL.
"""

import xml.etree.ElementTree as ET


def _text(element):
    return element.text.strip() if element is not None and element.text else ""


def _unwrap_autorizacion(root):
    """Unwrap an SRI ``<autorizacion>`` envelope into ``(document, auth)``."""
    auth = {
        "estado": _text(root.find("estado")),
        "numero_autorizacion": _text(root.find("numeroAutorizacion")),
        "fecha_autorizacion": _text(root.find("fechaAutorizacion")),
        "ambiente": _text(root.find("ambiente")),
    }
    comp = root.find("comprobante")
    if comp is None:
        raise ValueError("SRI autorizacion envelope carries no <comprobante>.")
    inner_xml = (comp.text or "").strip()
    if inner_xml.startswith("<"):
        return ET.fromstring(inner_xml), auth
    children = [child for child in comp if isinstance(child.tag, str)]
    if len(children) != 1:
        raise ValueError("SRI autorizacion <comprobante> carries no single document.")
    return children[0], auth


def parse_supplier_xml(xml_text):
    """Parse a bare ``<factura>`` or an ``<autorizacion>`` envelope.

    :return: dict with ``kind``, ``number``, ``emisor_ruc``,
        ``emisor_name``, ``clave_acceso``, ``issue_date`` (``DD/MM/YYYY``),
        ``currency``, ``taxes``, ``lines`` and ``autorizacion`` (or
        ``None`` for a bare document).
    :raises ValueError: on malformed XML, on a non-``factura`` document,
        or on any missing required block.
    """
    if not (xml_text or "").strip():
        raise ValueError("The supplier XML is empty.")
    try:
        root = ET.fromstring(xml_text.encode("utf-8"))
    except ET.ParseError as exc:
        raise ValueError(f"The supplier XML cannot be parsed: {exc}") from exc
    auth = None
    if root.tag == "autorizacion":
        root, auth = _unwrap_autorizacion(root)
    if root.tag != "factura":
        raise ValueError(
            f"Only supplier facturas can be imported as purchases, got '{root.tag}'."
        )
    return _parse_factura(root, auth)


def _parse_factura(root, auth):
    trib = root.find("infoTributaria")
    info = root.find("infoFactura")
    if trib is None or info is None:
        raise ValueError("The supplier factura carries no tax or header block.")
    number = "-".join(
        [
            _text(trib.find("estab")),
            _text(trib.find("ptoEmi")),
            _text(trib.find("secuencial")),
        ]
    ).strip("-")
    if not number:
        raise ValueError("The supplier XML carries no document number.")
    emisor_ruc = _text(trib.find("ruc"))
    if not emisor_ruc:
        raise ValueError("The supplier XML carries no emisor RUC.")
    clave = _text(trib.find("claveAcceso"))
    if not clave:
        raise ValueError(
            "The supplier XML carries no clave de acceso "
            "(offline doubles as auth number)."
        )
    lines = [_parse_line(line) for line in root.findall("detalles/detalle")]
    if not lines:
        raise ValueError("The supplier XML carries no detail lines.")
    reembolsos = root.findall("reembolsos/reembolsoDetalle")
    if reembolsos:
        raise ValueError("Supplier facturas with reembolsos need the manual path.")
    return {
        "kind": "factura",
        "number": number,
        "emisor_ruc": emisor_ruc,
        "emisor_name": _text(trib.find("razonSocial")),
        "clave_acceso": clave,
        "issue_date": _text(info.find("fechaEmision")),
        "currency": _text(info.find("moneda")),
        "total": _parse_float(info.find("importeTotal")),
        "taxes": [
            {
                "code": _text(row.find("codigo")),
                "rate_code": _text(row.find("codigoPorcentaje")),
                "base": _parse_float(row.find("baseImponible")),
                "value": _parse_float(row.find("valor")),
            }
            for row in info.findall("totalConImpuestos/totalImpuesto")
        ],
        "lines": lines,
        "autorizacion": auth,
    }


def _parse_float(element):
    text = _text(element).replace(",", ".")
    try:
        return float(text or 0)
    except ValueError:
        return 0.0


def _parse_line(line):
    return {
        "code": _text(line.find("codigoPrincipal")),
        "description": _text(line.find("descripcion")),
        "qty": _parse_float(line.find("cantidad")),
        "unit_price": _parse_float(line.find("precioUnitario")),
        "discount": _parse_float(line.find("descuento")),
        "total": _parse_float(line.find("precioTotalSinImpuesto")),
        "taxes": [
            {
                "code": _text(tax.find("codigo")),
                "rate_code": _text(tax.find("codigoPorcentaje")),
                "rate": _parse_float(tax.find("tarifa")),
                "base": _parse_float(tax.find("baseImponible")),
                "value": _parse_float(tax.find("valor")),
            }
            for tax in line.findall("impuestos/impuesto")
        ],
    }
