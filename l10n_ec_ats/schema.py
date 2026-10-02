"""Validation against the ATS schema published by the SRI.

``ats.xsd`` is authoritative for lexical shape, cardinality and patterns and
explicitly **not** authoritative for business rules: it is more permissive than
the SRI norm. It declares eight ``xsd:enumeration`` facets in total and none of
them is a VAT rate, a withholding concept or a document type, so passing this
validation is a grammar result and nothing more.

The helper is deliberately thin and caller-agnostic: it has no Odoo model, no
``ir.attachment``, no currency round-trip and no dependency on the wizard or the
builder, which do not exist yet. ATS-10 will call it while assembling the
document and ATS-11 will call it again as the first of the two validation
layers.
"""

from typing import NamedTuple

from lxml import etree

from odoo.tools import file_open

#: Location of the schema as published by the SRI, shipped unmodified.
ATS_XSD_PATH = "l10n_ec_ats/data/xsd/ats.xsd"


class AtsValidationResult(NamedTuple):
    """The outcome of validating one ATS document.

    The shape exists so that "not valid" can never collapse into "handled".
    ``_l10n_ec_action_check_xsd`` on ``account.edi.document`` can afford that
    conflation because the string it inspects was serialised in memory moments
    earlier and is implicitly byte-clean. An ATS document is assembled from
    SRI-validated catalog data and may be re-read from persisted text, so
    success and failure stay distinguishable at every call site.

    ``errors`` is empty exactly when ``is_valid`` is true.
    """

    is_valid: bool
    errors: tuple[str, ...]


def _ats_xsd_schema():
    """Compile the shipped schema.

    Resolution follows ``account.edi.document._l10n_ec_action_check_xsd`` --
    ``file_open``, ``etree.parse``, ``etree.XMLSchema`` -- so both EDI modules
    read the same way. The file is opened in binary mode because lxml requires
    it, and because reading it that way lets libxml2 apply its own BOM and
    encoding detection instead of Python's: the published artifact opens with a
    UTF-8 BOM while its declaration says ``encoding="ISO-8859-1"``, and the BOM
    wins. Re-decoding the bytes in Python first would hide that inconsistency
    instead of preserving it.
    """
    with file_open(ATS_XSD_PATH, "rb") as xsd_file:
        return etree.XMLSchema(etree.parse(xsd_file))


def validate_ats_xml(xml_string):
    """Validate one ATS document against the shipped schema.

    :param xml_string: the document, as ``str`` or ``bytes``. A ``str`` is
        encoded to UTF-8 first, because lxml refuses a unicode string that
        carries an XML declaration and every ATS document it will be given
        starts with one.
    :return: an :class:`AtsValidationResult`. Nothing is raised: an unparseable
        document is a verdict, not an exception, because the caller may be
        validating text it did not just build.
    :rtype: AtsValidationResult
    """
    if isinstance(xml_string, str):
        xml_string = xml_string.encode("utf-8")
    xsd_schema = _ats_xsd_schema()
    try:
        xml_doc = etree.fromstring(xml_string)
    except etree.XMLSyntaxError as error:
        return AtsValidationResult(False, (str(error),))
    try:
        xsd_schema.assert_(xml_doc)
    except AssertionError:
        # assert_ raises and fills error_log with the structured errors libxml2
        # collected; read them from there rather than re-parsing its message.
        return AtsValidationResult(
            False, tuple(str(entry) for entry in xsd_schema.error_log)
        )
    return AtsValidationResult(True, ())
