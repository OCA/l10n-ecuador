import logging
from base64 import b64decode
from random import randrange

import xmlsig  # pylint: disable=W7936
from cryptography.hazmat.primitives.serialization import pkcs12  # pylint: disable=W7936
from cryptography.x509 import ExtensionNotFound  # pylint: disable=W7936
from cryptography.x509.oid import ExtensionOID, NameOID  # pylint: disable=W7936
from lxml import etree
from xades import XAdESContext, template  # pylint: disable=W7936
from xades.policy import ImpliedPolicy  # pylint: disable=W7936

from odoo import api, fields, models, tools
from odoo.exceptions import UserError
from odoo.tools.translate import _

_logger = logging.getLogger(__name__)


class SriKeyType(models.Model):
    _name = "sri.key.type"
    _description = "Type of electronic key"

    name = fields.Char(size=255, required=True, readonly=False)
    file_content = fields.Binary(string="Signature File")
    file_name = fields.Char(string="Filename", readonly=True)
    password = fields.Char(string="Signing key")
    active = fields.Boolean(string="Active?", default=True)
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        default=lambda self: self.env.company,
    )
    state = fields.Selection(
        [
            ("unverified", "Unverified"),
            ("valid", "Valid Signature"),
            ("expired", "Signature Expired"),
        ],
        default="unverified",
        readonly=True,
    )
    # datos informativos del certificado
    issue_date = fields.Date(string="Date of issue", readonly=True)
    expire_date = fields.Date(string="Expiration date", readonly=True)
    subject_serial_number = fields.Char(string="Serial Number (Subject)", readonly=True)
    subject_common_name = fields.Char(string="Organization (Subject)", readonly=True)
    issuer_common_name = fields.Char(string="Organization (Issuer)", readonly=True)
    cert_serial_number = fields.Char(
        string="Serial number (certificate)", readonly=True
    )
    cert_version = fields.Char(string="Version", readonly=True)
    days_for_notification = fields.Integer(string="Days for notification", default=30)

    @tools.ormcache("self.id", "self.write_date", "self.password")
    def _decode_certificate(self):
        self.ensure_one()
        if not self.file_content or not self.password:
            return None

        try:
            file_content = b64decode(self.file_content)
        except Exception as ex:
            _logger.warning(f"Base64 decode failed: {ex}")
            raise UserError(_("Invalid certificate file (base64).")) from None

        try:
            private_key, cert, other_certs = pkcs12.load_key_and_certificates(
                file_content, self.password.encode("utf-8")
            )
        except Exception as ex:
            _logger.warning(f"PKCS#12 load failed: {ex}")
            raise UserError(
                _(
                    "Error opening the signature. Wrong password or unsupported file.\n"
                    f"{ex}"
                )
            ) from None

        if private_key is None or cert is None:
            raise UserError(
                _("PKCS#12 does not contain a private key and end-entity certificate.")
            )

        def has_digital_signature(x509):
            try:
                ku = x509.extensions.get_extension_for_oid(ExtensionOID.KEY_USAGE).value
                return bool(getattr(ku, "digital_signature", False))
            except ExtensionNotFound:
                return True

        if not has_digital_signature(cert) and other_certs:
            for other in other_certs:
                if has_digital_signature(other):
                    cert = other
                    break

        return (private_key, cert, other_certs or [])

    def action_validate_and_load(self):
        decoded = self._decode_certificate()
        if not decoded:
            raise UserError(_("Certificate/password not provided."))

        cert = decoded[1]

        issuer = cert.issuer
        subject = cert.subject

        def _attr(name_oid, xname):
            vals = xname.get_attributes_for_oid(name_oid)
            return vals[0].value if vals else ""

        subject_common_name = _attr(NameOID.COMMON_NAME, subject)
        subject_serial_number = _attr(NameOID.SERIAL_NUMBER, subject)
        issuer_common_name = _attr(NameOID.COMMON_NAME, issuer)

        vals = {
            "issue_date": fields.Datetime.context_timestamp(
                self, cert.not_valid_before
            ).date(),
            "expire_date": fields.Datetime.context_timestamp(
                self, cert.not_valid_after
            ).date(),
            "subject_common_name": subject_common_name,
            "subject_serial_number": subject_serial_number,
            "issuer_common_name": issuer_common_name,
            "cert_serial_number": cert.serial_number,
            "cert_version": str(cert.version),  # evita objetos Enum directos
            "state": "valid",
        }
        self.write(vals)
        return True

    def action_sign(self, xml_string_data):
        def new_range():
            return randrange(100000, 999999)

        p12 = self._decode_certificate()
        if not p12:
            raise UserError(_("Certificate/password not provided."))

        doc = etree.fromstring(xml_string_data)
        signature_id = f"Signature{new_range()}"
        signature_property_id = f"{signature_id}-SignedPropertiesID{new_range()}"
        certificate_id = f"Certificate{new_range()}"
        reference_uri = f"Reference-ID-{new_range()}"
        signature = xmlsig.template.create(
            xmlsig.constants.TransformInclC14N,
            xmlsig.constants.TransformRsaSha1,
            signature_id,
        )
        xmlsig.template.add_reference(
            signature,
            xmlsig.constants.TransformSha1,
            name=f"SignedPropertiesID{new_range()}",
            uri=f"#{signature_property_id}",
            uri_type="http://uri.etsi.org/01903#SignedProperties",
        )
        xmlsig.template.add_reference(
            signature, xmlsig.constants.TransformSha1, uri=f"#{certificate_id}"
        )
        ref = xmlsig.template.add_reference(
            signature,
            xmlsig.constants.TransformSha1,
            name=reference_uri,
            uri="#comprobante",
        )
        xmlsig.template.add_transform(ref, xmlsig.constants.TransformEnveloped)
        ki = xmlsig.template.ensure_key_info(signature, name=certificate_id)
        data = xmlsig.template.add_x509_data(ki)
        xmlsig.template.x509_data_add_certificate(data)
        xmlsig.template.add_key_value(ki)
        qualifying = template.create_qualifying_properties(signature, name=signature_id)
        props = template.create_signed_properties(
            qualifying, name=signature_property_id
        )
        signed_do = template.ensure_signed_data_object_properties(props)
        template.add_data_object_format(
            signed_do,
            f"#{reference_uri}",
            description="contenido comprobante",
            mime_type="text/xml",
        )
        doc.append(signature)
        ctx = XAdESContext(ImpliedPolicy(xmlsig.constants.TransformSha1))
        ctx.load_pkcs12(p12)
        ctx.sign(signature)
        ctx.verify(signature)
        return etree.tostring(doc, encoding="UTF-8", pretty_print=True).decode()

    def days_to_expire(self):
        if self.expire_date:
            return (self.expire_date - fields.Date.context_today(self)).days
        return 0

    @api.model
    def action_email_notification(self):
        email_template = self.env.ref(
            "l10n_ec_account_edi.email_template_notify", False
        )
        all_companies = self.env["res.company"].search([])
        for company in all_companies:
            certificates = self.search(
                [("company_id", "=", company.id), ("state", "=", "valid")]
            )
            for cert in certificates:
                if 0 < cert.days_to_expire() <= cert.days_for_notification:
                    email_template.send_mail(
                        cert.id, email_layout_xmlid="mail.mail_notification_light"
                    )
        return True
