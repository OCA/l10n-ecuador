from unittest.mock import patch

from odoo.tests import tagged

from odoo.addons.l10n_ec_account_edi.models.account_edi_document import (
    AccountEdiDocument,
)

from .sri_response import auth_sri_response, patch_service_sri
from .test_edi_common import TestL10nECEdiCommon

# The mocked SRI authorization response used by the default patch decorator
DUMMY_AUTHORIZATION_NUMBER = "DUMMY_ACCESS_KEY"


@tagged("post_install_l10n", "post_install", "-at_install")
class TestL10nEdiAuthorizationNumber(TestL10nECEdiCommon):
    def _authorization_data(self, edi_doc, estado="AUTORIZADO", with_number=True):
        """
        Build a single SRI authorization entry for the given EDI document
        :param edi_doc: Edi document for which the authorization is built
        :param estado: SRI authorization status, defaults to AUTORIZADO
        :param with_number: if False, omit the numeroAutorizacion key
        to emulate an SRI response that does not send the authorization number
        """
        xml_file = edi_doc._l10n_ec_render_xml_edi()
        xml_signed = self.company.l10n_ec_key_type_id.action_sign(xml_file)
        authorization = self._get_default_response_auth(
            edi_doc.l10n_ec_xml_access_key, xml_signed
        )
        authorization["estado"] = estado
        if not with_number:
            del authorization["numeroAutorizacion"]
        return authorization

    def _response_with_auth(self, edi_doc, **kwargs):
        """
        Build the full SRI authorization response wrapping a single
        authorization entry built by _authorization_data
        """
        return {
            "claveAccesoConsultada": edi_doc.l10n_ec_xml_access_key,
            "numeroComprobantes": 1,
            "autorizaciones": {
                "autorizacion": [self._authorization_data(edi_doc, **kwargs)]
            },
        }

    @patch_service_sri
    def test_l10n_ec_authorization_number_stored_on_edi_document(self):
        """Authorization number is persisted on the EDI document"""
        self._setup_edi_company_ec()
        invoice = self._l10n_ec_prepare_edi_out_invoice(auto_post=True)
        edi_doc = invoice._get_edi_document(self.edi_format)
        edi_doc._process_documents_web_services(with_commit=False)
        self.assertEqual(edi_doc.state, "sent")
        self.assertEqual(
            auth_sri_response.autorizaciones.autorizacion[0].numeroAutorizacion,
            DUMMY_AUTHORIZATION_NUMBER,
        )
        self.assertEqual(
            edi_doc.l10n_ec_authorization_number, DUMMY_AUTHORIZATION_NUMBER
        )

    @patch_service_sri
    def test_l10n_ec_authorization_number_mirrored_on_move(self):
        """Authorization number is mirrored on the account move"""
        self._setup_edi_company_ec()
        invoice = self._l10n_ec_prepare_edi_out_invoice(auto_post=True)
        edi_doc = invoice._get_edi_document(self.edi_format)
        edi_doc._process_documents_web_services(with_commit=False)
        self.assertTrue(edi_doc.l10n_ec_authorization_number)
        self.assertEqual(
            invoice.l10n_ec_authorization_number,
            edi_doc.l10n_ec_authorization_number,
        )
        self.assertEqual(
            invoice.l10n_ec_authorization_number, DUMMY_AUTHORIZATION_NUMBER
        )

    @patch_service_sri
    def test_l10n_ec_authorization_number_not_stored_when_not_authorized(self):
        """A non authorized response does not store the authorization number"""

        def mock_edi_send_xml_auth_rejected(edi_doc_instance, client_ws):
            # numeroAutorizacion is deliberately kept to prove the value is
            # only persisted from the authorized branch
            return self._response_with_auth(edi_doc_instance, estado="RECHAZADO")

        self._setup_edi_company_ec()
        invoice = self._l10n_ec_prepare_edi_out_invoice(auto_post=True)
        edi_doc = invoice._get_edi_document(self.edi_format)
        with patch.object(
            AccountEdiDocument,
            "_l10n_ec_edi_send_xml_auth",
            mock_edi_send_xml_auth_rejected,
        ):
            edi_doc._process_documents_web_services(with_commit=False)
        self.assertNotEqual(edi_doc.state, "sent")
        self.assertFalse(edi_doc.l10n_ec_authorization_date)
        self.assertFalse(edi_doc.l10n_ec_authorization_number)

    @patch_service_sri
    def test_l10n_ec_authorization_number_missing_in_response(self):
        """An authorized response without numeroAutorizacion stores False"""

        def mock_edi_send_xml_auth_without_number(edi_doc_instance, client_ws):
            return self._response_with_auth(edi_doc_instance, with_number=False)

        self._setup_edi_company_ec()
        invoice = self._l10n_ec_prepare_edi_out_invoice(auto_post=True)
        edi_doc = invoice._get_edi_document(self.edi_format)
        with patch.object(
            AccountEdiDocument,
            "_l10n_ec_edi_send_xml_auth",
            mock_edi_send_xml_auth_without_number,
        ):
            edi_doc._process_documents_web_services(with_commit=False)
        # the document was authorized, only the number was absent
        self.assertEqual(edi_doc.state, "sent")
        self.assertTrue(edi_doc.l10n_ec_authorization_date)
        self.assertFalse(edi_doc.l10n_ec_authorization_number)
