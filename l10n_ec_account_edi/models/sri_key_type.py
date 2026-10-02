import logging
from base64 import b64decode
from random import randrange

import xmlsig
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509 import ExtensionNotFound
from cryptography.x509.oid import ExtensionOID, NameOID
from lxml import etree
from xades import XAdESContext, template
from xades.policy import ImpliedPolicy

from odoo import api, fields, models, tools
from odoo.exceptions import UserError

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
    subject_serial_number = fields.Char(string="Serial Number(Subject)", readonly=True)
    subject_common_name = fields.Char(string="Organization(Subject)", readonly=True)
    issuer_common_name = fields.Char(string="Organization (Issuer)", readonly=True)
    cert_serial_number = fields.Char(
        string="Serial number (certificate)", readonly=True
    )
    cert_version = fields.Char(string="Version", readonly=True)
    days_for_notification = fields.Integer(string="Days for notification", default=30)

    @tools.ormcache("self.file_content", "self.password", "self.state")
    def _decode_certificate(self):
        self.ensure_one()
        if not self.password:
            return None, None, None
        file_content = b64decode(self.file_content)
        try:
            private_key, certificate, additional_certs = (
                pkcs12.load_key_and_certificates(file_content, self.password.encode())
            )
        except Exception as ex:
            # Debug, not warning: a wrong signing password is an expected user
            # input error surfaced as a UserError, and the OCA checklog fails a
            # run on logged warnings.
            self._l10n_ec_log_exception(_logger.debug, ex)
            raise UserError(
                self.env._(
                    "Error opening the signature, possibly the signature key has "
                    "been entered incorrectly or the file is not supported. \n%s",
                    ex,
                )
            ) from None
        # revisar si el certificado tiene la extension digital_signature activada
        # caso contrario tomar del listado de certificados el primero que tengan esta
        # extension
        is_digital_signature = True
        try:
            extension = certificate.extensions.get_extension_for_oid(
                ExtensionOID.KEY_USAGE
            )
            is_digital_signature = extension.value.digital_signature
        except ExtensionNotFound as ex:
            self._l10n_ec_log_exception(_logger.debug, ex)
        if not is_digital_signature:
            # cuando hay mas de un certificado, tomar el certificado correcto
            # este deberia tener entre las extensiones digital_signature = True
            # pero si el certificado solo tiene uno, devolvera None
            for other_cert in additional_certs or ():
                try:
                    extension = other_cert.extensions.get_extension_for_oid(
                        ExtensionOID.KEY_USAGE
                    )
                except ExtensionNotFound as ex:
                    self._l10n_ec_log_exception(_logger.debug, ex)
                    continue
                if extension.value.digital_signature:
                    certificate = other_cert
                    break
        return private_key, certificate

    def _l10n_ec_log_exception(self, log, ex):
        """Log an exception without ``tools.ustr``, deprecated since Odoo 18.

        ``%s`` already coerces the exception, so the conversion is redundant.
        """
        log("%s", ex)

    def _l10n_ec_cert_date(self, cert, naive_attr):
        """Return a certificate validity date as a naive date in the user timezone.

        ``cryptography`` exposes the aware ``*_utc`` attributes only from 42,
        and deprecates the naive ones from 42, so both are supported here.
        """
        aware_attr = f"{naive_attr}_utc"
        if hasattr(cert, aware_attr):
            return getattr(cert, aware_attr).astimezone(self.env.tz).date()
        return fields.Datetime.context_timestamp(self, getattr(cert, naive_attr)).date()

    def action_validate_and_load(self):
        _private_key, cert = self._decode_certificate()
        issuer = cert.issuer
        subject = cert.subject
        subject_common_name = (
            subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
            if subject.get_attributes_for_oid(NameOID.COMMON_NAME)
            else ""
        )
        subject_serial_number = (
            subject.get_attributes_for_oid(NameOID.SERIAL_NUMBER)[0].value
            if subject.get_attributes_for_oid(NameOID.SERIAL_NUMBER)
            else ""
        )
        issuer_common_name = (
            issuer.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
            if subject.get_attributes_for_oid(NameOID.COMMON_NAME)
            else ""
        )
        vals = {
            # ``not_valid_before_utc`` only exists from cryptography 42, and the
            # naive ``not_valid_before`` is deprecated from 42, so support both.
            # The aware value is converted with ``astimezone`` rather than
            # ``fields.Datetime.context_timestamp``, which requires a naive UTC
            # value (``pytz.utc.localize``) and raises on an aware datetime.
            "issue_date": self._l10n_ec_cert_date(cert, "not_valid_before"),
            "expire_date": self._l10n_ec_cert_date(cert, "not_valid_after"),
            "subject_common_name": subject_common_name,
            "subject_serial_number": subject_serial_number,
            "issuer_common_name": issuer_common_name,
            "cert_serial_number": cert.serial_number,
            "cert_version": cert.version,
            "state": "valid",
        }
        self.write(vals)
        return True

    def action_sign(self, xml_string_data):
        def new_range():
            return randrange(100000, 999999)

        p12 = self._decode_certificate()
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
        # Do not use ctx.load_pkcs12() here. It is unreachable on pyOpenSSL >= 24:
        # the library still evaluates ``OpenSSL.crypto.PKCS12``, which pyOpenSSL
        # 24 removed, so the call raises AttributeError before it can dispatch to
        # its own tuple branch. Assigning the context attributes is exactly what
        # that unreachable branch does.
        ctx.x509 = p12[1]
        ctx.public_key = p12[1].public_key()
        ctx.private_key = p12[0]
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
        all_companies = self.env["res.company"].search_fetch([])
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
