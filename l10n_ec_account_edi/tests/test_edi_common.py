import base64
from datetime import datetime

import pytz

from odoo.tests import tagged
from odoo.tools import misc, os

from odoo.addons.account_edi.tests.common import AccountEdiTestCommon

from .test_common import TestL10nECCommon


@tagged("post_install_l10n", "post_install", "-at_install")
class TestL10nECEdiCommon(AccountEdiTestCommon, TestL10nECCommon):
    @classmethod
    def setUpClass(
        cls,
        chart_template_ref="l10n_ec.l10n_ec_ifrs",
        edi_format_ref="l10n_ec_account_edi.edi_format_ec_sri",
    ):
        super().setUpClass(
            chart_template_ref=chart_template_ref, edi_format_ref=edi_format_ref
        )
        cls.env.user.tz = "America/Guayaquil"
        # Archivo xml básico
        cls.attachment = cls.env["ir.attachment"].create(
            {
                "name": "invoice.xml",
                "datas": base64.encodebytes(
                    b"<?xml version='1.0' encoding='UTF-8'?><Invoice/>"
                ),
                "mimetype": "application/xml",
            }
        )

        file_path = os.path.join(
            "l10n_ec_account_edi", "tests", "certificates", "test.p12"
        )
        file_content = misc.file_open(file_path, mode="rb").read()
        # Crear certificado de firma electrónica válido
        cls.certificate = (
            cls.env["sri.key.type"]
            .sudo()
            .create(
                {
                    "name": "Test",
                    "file_name": "test.p12",
                    "password": "123456",
                    "file_content": base64.b64encode(file_content),
                    "company_id": cls.company_data["company"].id,
                },
            )
        )

    def _setup_edi_company_ec(self):
        """Configurar datos de compañia para facturación electronica"""
        self._setup_company_ec()
        self.certificate.action_validate_and_load()
        self.company.write(
            {
                "l10n_ec_type_environment": "test",
                "l10n_ec_key_type_id": self.certificate.id,
                "l10n_ec_invoice_version": "1.1.0",
            }
        )
        self.journal_sale.write(
            {
                "l10n_ec_emission_address_id": self.partner_contact.id,
                "l10n_ec_sri_payment_id": self.env.ref("l10n_ec.P1").id,
                "l10n_latam_use_documents": True,
                "l10n_ec_entity": "001",
                "l10n_ec_emission": "001",
                "l10n_ec_emission_type": "electronic",
            }
        )
        # diario para Liq. de compra
        self.journal_purchase.write(
            {
                "l10n_ec_emission_address_id": self.partner_contact.id,
                "l10n_ec_sri_payment_id": self.env.ref("l10n_ec.P1").id,
                "l10n_latam_use_documents": True,
                "l10n_ec_entity": "001",
                "l10n_ec_emission": "001",
                "l10n_ec_emission_type": "electronic",
            }
        )
        # Diario efectivo, establecer tipo de pago SRI
        self.journal_cash.l10n_ec_sri_payment_id = self.env.ref("l10n_ec.P1").id
        self.tax_sale_a.write(
            {
                "l10n_ec_xml_fe_code": "2",
                "tax_group_id": self.env.ref("l10n_ec.tax_group_vat_12").id,
            }
        )

    def _l10n_ec_prepare_edi_out_invoice(
        self,
        partner=None,
        taxes=None,
        products=None,
        journal=None,
        latam_document_type=None,
        use_payment_term=True,
        auto_post=False,
    ):
        """Crea y devuelve una factura de venta electronica
        :param partner: Partner, si no se envia se coloca uno
        :param taxes: Impuestos, si no se envia se coloca impuestos del producto
        :param products: Productos, si no se envia se coloca uno
        :param journal: Diario, si no se envia se coloca
        por defecto diario para factura de venta
        :param latam_document_type: Tipo de documento, si no se envia se coloca uno
        :param use_payment_term: Si es True se coloca
        un término de pago a la factura, por defecto True
        :param auto_post: Si es True valida la factura
        y la devuelve en estado posted, por defecto False
        """
        partner = partner or self.partner_cf
        latam_document_type = latam_document_type or self.env.ref("l10n_ec.ec_dt_18")
        form = self._l10n_ec_create_form_move(
            move_type="out_invoice",
            internal_type="invoice",
            partner=partner,
            taxes=taxes,
            products=products,
            journal=journal,
            latam_document_type=latam_document_type,
            use_payment_term=use_payment_term,
        )
        invoice = form.save()
        if auto_post:
            invoice.action_post()
        return invoice

    def _l10n_ec_test_generate_access_key(self, edi_doc):
        """Genera y devuelve una clave de acceso
        :param edi_doc: Edi document para obtener los datos"""
        environment = edi_doc._l10n_ec_get_environment()
        document_code_sri = edi_doc._l10n_ec_get_edi_code_sri()
        document_number = edi_doc._l10n_ec_get_edi_number().replace("-", "")
        date_document = edi_doc._l10n_ec_get_edi_date()
        access_key = edi_doc.l10n_ec_generate_access_key(
            document_code_sri=document_code_sri,
            complete_document_number=document_number,
            environment=environment,
            date_document=date_document,
            company=self.company,
        )
        return access_key

    def _get_response_with_auth(self, edi_doc):
        """
        simular la respuesta del SRI como si el documento se haya autorizado
        """
        # mandar a generar el xml para poder adjuntarlo a la respuesta del SRI
        xml_file = edi_doc._l10n_ec_render_xml_edi()
        xml_signed = self.company.l10n_ec_key_type_id.action_sign(xml_file)
        return {
            "claveAccesoConsultada": edi_doc.l10n_ec_xml_access_key,
            "numeroComprobantes": 1,
            "autorizaciones": {
                "autorizacion": [
                    self._get_default_response_auth(
                        edi_doc.l10n_ec_xml_access_key, xml_signed
                    )
                ]
            },
        }

    def _get_response_without_auth(self, edi_doc):
        """
        simular la respuesta del SRI donde no se obtenga autorizacion
        """
        # mandar a generar el xml para poder adjuntarlo a la respuesta del SRI
        xml_file = edi_doc._l10n_ec_render_xml_edi()
        self.company.l10n_ec_key_type_id.action_sign(xml_file)
        return {
            "claveAccesoConsultada": edi_doc.l10n_ec_xml_access_key,
            "numeroComprobantes": 1,
            "autorizaciones": {},
        }

    def _get_default_response_auth(self, access_key, xml_file):
        return {
            "ambiente": "PRUEBAS"
            if self.company.l10n_ec_type_environment == "test"
            else "PRODUCCION",
            "estado": "AUTORIZADO",
            "numeroAutorizacion": access_key,
            "fechaAutorizacion": datetime.now(pytz.timezone("America/Guayaquil")),
            "mensajes": None,
            "comprobante": xml_file,
        }
