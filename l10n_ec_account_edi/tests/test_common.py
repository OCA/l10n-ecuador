from datetime import datetime

from odoo import fields
from odoo.tests import Form, tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install_l10n", "post_install", "-at_install")
class TestL10nECCommon(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(
        cls,
        chart_template_ref="l10n_ec.l10n_ec_ifrs",
    ):
        super().setUpClass(chart_template_ref=chart_template_ref)
        cls.company = cls.company_data["company"]
        cls.company.write(
            {
                "l10n_ec_invoice_version": False,
                "country_id": cls.env.ref("base.ec").id,
            }
        )
        # Models
        cls.Partner = cls.env["res.partner"].with_company(cls.company).sudo()
        cls.Journal = cls.env["account.journal"].with_company(cls.company)
        cls.AccountMove = cls.env["account.move"].with_company(cls.company)
        cls.AccountFiscalPosition = cls.env["account.fiscal.position"].with_company(
            cls.company
        )
        cls.Tax = cls.env["account.tax"].with_company(cls.company)
        cls.TaxGroup = cls.env["account.tax.group"].with_company(cls.company)
        # Dates
        cls.current_datetime = fields.Datetime.context_timestamp(
            cls.AccountMove, fields.Datetime.now()
        )
        cls.current_date = fields.Date.context_today(cls.AccountMove)
        # Partners
        cls.partner_contact = cls.company.partner_id
        cls.partner_cf = cls.Partner.create(
            {
                "name": "Consumidor Final",
                "vat": "9999999999999",
                "country_id": cls.env.ref("base.ec").id,
            }
        )
        cls.partner_dni = cls.Partner.create(
            {
                "name": "Test Partner DNI",
                "vat": "1313109678",
                "l10n_latam_identification_type_id": cls.env.ref("l10n_ec.ec_dni").id,
                "country_id": cls.env.ref("base.ec").id,
            }
        )
        cls.partner_ruc = cls.Partner.create(
            {
                "name": "Test Partner RUC",
                "vat": "1313109678001",
                "l10n_latam_identification_type_id": cls.env.ref("l10n_ec.ec_ruc").id,
                "country_id": cls.env.ref("base.ec").id,
            }
        )
        cls.partner_passport = cls.Partner.create(
            {
                "name": "Test Partner Passport",
                "vat": "12345678",
                "l10n_latam_identification_type_id": cls.env.ref(
                    "l10n_ec.ec_passport"
                ).id,
                "country_id": cls.env.ref("base.co").id,
            }
        )
        cls.partner_with_email = cls.Partner.create(
            {
                "name": "SERVICIO DE RENTAS INTERNAS",
                "vat": "1760013210001",
                "l10n_latam_identification_type_id": cls.env.ref("l10n_ec.ec_ruc").id,
                "country_id": cls.env.ref("base.ec").id,
                "email": "my_email@test.com.ec",
            }
        )
        # Impuestos
        cls.tax_group_vat = cls.TaxGroup.search(
            [("l10n_ec_type", "=", "vat12")], limit=1
        )
        cls.taxes_zero_vat = cls.Tax.search(
            [("tax_group_id.l10n_ec_type", "=", "zero_vat")], limit=2
        )
        cls.taxes_vat = cls.Tax.search(
            [("tax_group_id", "=", cls.tax_group_vat.id)], limit=2
        )
        cls.tax_not_charged_vat = cls.Tax.search(
            [("tax_group_id.l10n_ec_type", "=", "not_charged_vat")], limit=1
        )
        cls.tax_exempt_vat = cls.Tax.search(
            [("tax_group_id.l10n_ec_type", "=", "exempt_vat")], limit=1
        )
        cls.tax_group_withhold_vat = cls.TaxGroup.search(
            [("l10n_ec_type", "=", "withhold_vat")], limit=1
        )
        cls.tax_group_withhold_profit = cls.TaxGroup.search(
            [("l10n_ec_type", "=", "withhold_income_tax")], limit=1
        )
        # Diarios
        cls.journal_sale = cls.company_data["default_journal_sale"]
        cls.journal_purchase = cls.company_data["default_journal_purchase"]
        cls.journal_cash = cls.company_data["default_journal_cash"]

        # Number authorization
        cls.number_authorization_electronic = "".rjust(49, "1")

    def get_sequence_number(self):
        """Generar secuencia para documentos y que no se repitan"""
        return "001-001-0{}".format(datetime.now().strftime("%S%f"))

    def _setup_company_ec(self):
        """Configurar datos para compañia ecuatoriana"""
        self.company.write(
            {
                "vat": "1313109678001",
                "currency_id": self.env.ref("base.USD").id,
            }
        )
        # Agregar tipo de contribuyente, obligado a llevar contabilidad, y emitir retenciones
        required_accounting = self.AccountFiscalPosition.search(
            [("name", "like", "Persona natural obligada a llevar contabilidad")]
        )
        self.partner_contact.write(
            {
                "l10n_latam_identification_type_id": self.env.ref("l10n_ec.ec_ruc").id,
                "street": "SN",
                "property_account_position_id": required_accounting.id,
            }
        )

    def _l10n_ec_edi_company_no_account(self):
        """Cambiar tipo de contribuyente, compañia no
        obligada a llevar contabilidad, no validar impuestos de retenciones"""
        not_required_accounting = (
            self.env["account.fiscal.position"]
            .with_company(self.company_data["company"])
            .search([("name", "like", "Persona natural no obligadas")])
        )
        self.partner_contact.write(
            {"property_account_position_id": not_required_accounting.id}
        )

    def _l10n_ec_create_form_move(
        self,
        move_type,
        internal_type,
        partner,
        taxes=None,
        products=None,
        journal=None,
        latam_document_type=None,
        use_payment_term=False,
        form_id=None,
    ):
        """Método base con datos genericos para crear formulario de:
         Faturas, notas de crédito,debito, liquidaciones y retenciones de venta
        :param move_type: Tipo de documento (in_invoice,out_invoice,in_refund, out_refund)
        :param internal_type: Tipo interno del documento(invoice,credit_note)
        :param partner: Partner del documento
        :param number: Número del documento, si no se envia se coloca uno
        :param taxes: Impuestos, Por defecto se toma impuestos del producto
        :param products: Productos, si no se envia, se colocará un producto
        :param journal: Diario, si no se envia por defecto coloca uno
         según el internal_type y move_type; campo requerido
        :param latam_document_type: Tipo de documento, si no se envia por defecto
         coloca uno según el partner y journal; campo requerido
        :param use_payment_term: Si es True, colocará un término de pago en el documento,
          por defecto False
        :param form_id: ID del formulario si fuese diferente al de la factura,
          por defecto None
        """
        products = products or self.product_a
        move_form = Form(
            self.AccountMove.with_context(
                default_move_type=move_type,
                internal_type=internal_type,
                mail_create_nosubscribe=True,
            ),
            form_id,
        )
        move_form.invoice_date = fields.Date.context_today(self.AccountMove)
        move_form.partner_id = partner
        if journal:
            move_form.journal_id = journal
        if latam_document_type:
            move_form.l10n_latam_document_type_id = latam_document_type
        if use_payment_term:
            move_form.invoice_payment_term_id = self.env.ref(
                "account.account_payment_term_15days"
            )
        move_form.l10n_latam_document_number = self.get_sequence_number()
        for product in products or []:
            with move_form.invoice_line_ids.new() as line_form:
                line_form.product_id = product
                if taxes:
                    line_form.tax_ids.clear()
                    for tax in taxes:
                        line_form.tax_ids.add(tax)
        return move_form

    def _l10n_ec_create_in_invoice(
        self,
        partner=None,
        taxes=None,
        products=None,
        journal=None,
        latam_document_type=None,
        auto_post=False,
    ):
        """Crea y devuelve una factura de compra
        :param partner: Partner, si no se envia se coloca uno
        :param taxes: Impuestos, si no se envia se coloca impuestos del producto
        :param products: Productos, si no se envia se coloca uno
        :param journal: Diario, si no se envia se coloca por
         defecto diario para factura de compra
        :latam_document_type: Tipo de documento, si no se envia se coloca uno
        :auto_post: Si es True valida la factura y
        la devuelve en estado posted, por defecto False
        """
        partner = partner or self.partner_ruc
        latam_document_type = latam_document_type or self.env.ref("l10n_ec.ec_dt_18")
        form = self._l10n_ec_create_form_move(
            move_type="in_invoice",
            internal_type="invoice",
            partner=partner,
            taxes=taxes,
            products=products,
            journal=journal,
            latam_document_type=latam_document_type,
            use_payment_term=True,
        )
        form.l10n_ec_electronic_authorization = self.number_authorization_electronic
        invoice = form.save()
        if auto_post:
            invoice.action_post()
        return invoice

    def generate_payment(self, invoice_ids, journal=False, amount=False):
        """Genera pago para facturas
        :param invoice_ids: Ids de facturas para realizar pago
        :param journal: Diario, para realizar el pago, por defecto se coloca diario banco
        :param amount: Monto del pago, Si no se coloca se realiza el pago total de la factura"""
        wizard_payment = self.env["account.payment.register"].with_context(
            active_model="account.move", active_ids=invoice_ids
        )
        with Form(wizard_payment) as form:
            if journal:
                form.journal_id = journal
            else:
                form.l10n_ec_sri_payment_id = self.env.ref("l10n_ec.P20")
            if amount:
                form.amount = amount
        payment = form.save()
        payment._create_payments()
        return payment
