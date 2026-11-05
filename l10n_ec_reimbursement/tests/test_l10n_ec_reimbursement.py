"""Reimbursed voucher legs: constraints, EDI blocks on 01/03, ATS total.

The three consumers of a leg are pinned separately: the model refuses a
mixed code, a missing identification and an empty base; the EDI values
render ``reembolsoDetalle`` plus totals inside factura 01 and liquidación
03; and the ATS collector row carries ``totbasesImpReemb`` while the
document's own buckets stay untouched.
"""

from datetime import date

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from odoo.addons.l10n_ec_account_edi.tests.test_edi_common import (
    TestL10nECEdiCommon,
)

FORM_ID = "l10n_ec_account_edi.account_invoice_liquidation_purchase_form_view"


@tagged("post_install_l10n", "post_install", "-at_install")
class TestL10nEcReimbursement(TestL10nECEdiCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls()._setup_edi_company_ec()

    def _add_reimbursement(self, move, **overrides):
        values = {
            "doc_code": "01",
            "supplier_id_type": "04",
            "supplier_id": "1790012345001",
            "sri_number": "001-002-000000003",
            "issue_date": date(2026, 3, 4),
            "auth_number": "1" * 49,
            "base_amount": 100.0,
            "taxed_base": 100.0,
            "iva_amount": 15.0,
        }
        values.update(overrides)
        values["move_id"] = move.id
        return self.env["l10n.ec.reimbursement.detail"].create(values)

    def _l10n_ec_prepare_edi_liquidation(self, auto_post=False):
        form = self._l10n_ec_create_form_move(
            move_type="in_invoice",
            internal_type="purchase_liquidation",
            partner=self.partner_dni,
            latam_document_type=self.env.ref("l10n_ec.ec_dt_03"),
            use_payment_term=True,
            form_id=FORM_ID,
        )
        invoice = form.save()
        if auto_post:
            self._post_with_support(invoice)
        return invoice

    def _post_with_support(self, move):
        """Post a purchase document with its tax support captured.

        ``l10n_ec_withhold`` refuses to post a purchase document with no
        tax support, so the tests capture sustento ``01`` first -- the
        support the ATS collector later validates against the catalogue.
        """
        move.l10n_ec_tax_support = "01"
        move.action_post()
        return move

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------

    def test_single_doc_code_constraint(self):
        """Legs on one document share a single SRI code; mixing refuses."""
        move = self._l10n_ec_create_in_invoice()
        self._add_reimbursement(move)
        self._add_reimbursement(move, sri_number="001-002-000000004")
        with self.assertRaises(ValidationError):
            self._add_reimbursement(move, doc_code="03")

    def test_mixed_codes_single_write_refusal(self):
        """Two mixed legs written at once refuse together, not one by one."""
        move = self._l10n_ec_create_in_invoice()
        with self.assertRaises(ValidationError):
            move.write(
                {
                    "reimbursement_ids": [
                        (
                            0,
                            0,
                            {
                                "doc_code": "01",
                                "supplier_id_type": "04",
                                "supplier_id": "1790012345001",
                                "sri_number": "001-002-000000003",
                                "issue_date": date(2026, 3, 4),
                                "auth_number": "1" * 49,
                                "base_amount": 100.0,
                            },
                        ),
                        (
                            0,
                            0,
                            {
                                "doc_code": "03",
                                "supplier_id_type": "04",
                                "supplier_id": "1790012345001",
                                "sri_number": "001-002-000000005",
                                "issue_date": date(2026, 3, 4),
                                "auth_number": "1" * 49,
                                "base_amount": 50.0,
                            },
                        ),
                    ]
                }
            )

    def test_missing_supplier_refusal(self):
        """Legs without the supplier's identification or authorization refuse."""
        move = self._l10n_ec_create_in_invoice()
        base = {
            "move_id": move.id,
            "doc_code": "01",
            "supplier_id_type": "04",
            "supplier_id": "1790012345001",
            "sri_number": "001-002-000000003",
            "issue_date": date(2026, 3, 4),
            "auth_number": "1" * 49,
            "base_amount": 100.0,
        }
        Detail = self.env["l10n.ec.reimbursement.detail"]
        for missing in ("supplier_id", "auth_number"):
            values = {k: v for k, v in base.items() if k != missing}
            with self.assertRaises(ValidationError):
                Detail.create(values)

    def test_write_null_refusal(self):
        """Blanking a required leg value refuses; other writes pass."""
        move = self._l10n_ec_create_in_invoice()
        leg = self._add_reimbursement(move)
        with self.assertRaises(ValidationError):
            leg.write({"supplier_id": False})
        leg.write({"base_amount": 120.0})
        self.assertEqual(leg.base_amount, 120.0)

    def test_zero_bases_refusal(self):
        """A leg with no base at all refuses, even with taxes on it."""
        move = self._l10n_ec_create_in_invoice()
        with self.assertRaises(ValidationError):
            self._add_reimbursement(
                move,
                base_amount=0.0,
                taxed_base=0.0,
                no_tax_base=0.0,
                exempt_base=0.0,
                iva_amount=15.0,
            )

    def test_untaxed_base_passes(self):
        """A taxed-base-only leg passes: one base above zero is enough."""
        move = self._l10n_ec_create_in_invoice()
        leg = self._add_reimbursement(
            move, base_amount=0.0, taxed_base=200.0, iva_amount=30.0
        )
        self.assertEqual(leg.taxed_base, 200.0)

    # ------------------------------------------------------------------
    # EDI: factura 01
    # ------------------------------------------------------------------

    def _render_invoice_xml(self, move):
        """Render factura 01 for a vendor bill through the values seam.

        Vendor bills carry no ``account.edi.document`` of their own, so the
        values builder runs on a transient document and the base template is
        rendered directly -- the same two pieces posting wires together.
        """
        edi_doc = self.env["account.edi.document"].new(
            {"move_id": move.id, "edi_format_id": self.edi_format.id}
        )
        values = edi_doc._l10n_ec_get_info_invoice()
        return (
            self.env["ir.ui.view"]
            .sudo()
            ._render_template("l10n_ec_account_edi.ec_edi_invoice", values)
        )

    def test_reembolso_xml_01(self):
        """A vendor bill with legs renders reembolsoDetalle plus totals."""
        move = self._post_with_support(self._l10n_ec_create_in_invoice())
        self._add_reimbursement(move)
        xml = self._render_invoice_xml(move)
        self.assertIn("<reembolsoDetalle>", xml)
        self.assertIn("<codDocReembolso>01</codDocReembolso>", xml)
        self.assertIn(
            "<totalComprobantesReembolso>1.00</totalComprobantesReembolso>", xml
        )
        self.assertIn(
            "<totalBaseImponibleReembolso>100.00</totalBaseImponibleReembolso>", xml
        )
        self.assertIn("<totalImpuestoReembolso>15.00</totalImpuestoReembolso>", xml)
        self.assertIn("<estabDocReembolso>001</estabDocReembolso>", xml)
        self.assertIn("<ptoEmiDocReembolso>002</ptoEmiDocReembolso>", xml)
        self.assertIn("<secuencialDocReembolso>000000003</secuencialDocReembolso>", xml)
        self.assertIn(
            "<fechaEmisionDocReembolso>04/03/2026</fechaEmisionDocReembolso>", xml
        )
        self.assertIn("<codigoPorcentaje>4</codigoPorcentaje>", xml)
        self.assertIn(
            "<numeroautorizacionDocReemb>" + "1" * 49 + "</numeroautorizacionDocReemb>",
            xml,
        )
        # Totals sit inside the info block, the block after the lines.
        self.assertLess(
            xml.index("<totalComprobantesReembolso>"),
            xml.index("</infoFactura>"),
        )
        self.assertLess(xml.index("</detalles>"), xml.index("<reembolsos>"))

    def test_no_legs_no_block_01(self):
        """A bill without legs renders no reembolso nodes at all."""
        move = self._post_with_support(self._l10n_ec_create_in_invoice())
        xml = self._render_invoice_xml(move)
        self.assertIn("<infoFactura>", xml)
        self.assertNotIn("reembolso", xml)
        self.assertNotIn("Reembolso", xml)

    # ------------------------------------------------------------------
    # EDI: liquidation 03
    # ------------------------------------------------------------------

    def test_reembolso_xml_03(self):
        """A purchase liquidation with legs renders the same block on 03."""
        move = self._l10n_ec_prepare_edi_liquidation(auto_post=True)
        self._add_reimbursement(move, doc_code="03")
        edi_doc = move._get_edi_document(self.edi_format)
        xml = edi_doc._l10n_ec_render_xml_edi()
        self.assertIn("<reembolsoDetalle>", xml)
        self.assertIn("<codDocReembolso>03</codDocReembolso>", xml)
        self.assertIn(
            "<totalComprobantesReembolso>1.00</totalComprobantesReembolso>", xml
        )
        self.assertIn(
            "<totalBaseImponibleReembolso>100.00</totalBaseImponibleReembolso>", xml
        )
        self.assertIn("<totalImpuestoReembolso>15.00</totalImpuestoReembolso>", xml)
        self.assertLess(
            xml.index("<totalComprobantesReembolso>"),
            xml.index("</infoLiquidacionCompra>"),
        )
        self.assertLess(xml.index("</detalles>"), xml.index("<reembolsos>"))

    def test_bad_sri_number_refuses_emission(self):
        """A malformed voucher number refuses the emission, not the posting."""
        move = self._l10n_ec_prepare_edi_liquidation(auto_post=True)
        self._add_reimbursement(move, doc_code="03", sri_number="001-002-42")
        edi_doc = move._get_edi_document(self.edi_format)
        with self.assertRaises(ValidationError):
            edi_doc._l10n_ec_render_xml_edi()

    def test_ice_leg_refuses_emission(self):
        """An ICE leg refuses the emission: v1 has no tariff-code source."""
        move = self._post_with_support(self._l10n_ec_create_in_invoice())
        self._add_reimbursement(move, ice_amount=5.0)
        with self.assertRaisesRegex(UserError, "ICE"):
            self._render_invoice_xml(move)

    def test_iva_without_taxed_base_refuses(self):
        """IVA with no taxed base derives no rate and refuses emission."""
        move = self._post_with_support(self._l10n_ec_create_in_invoice())
        self._add_reimbursement(move, taxed_base=0.0, no_tax_base=50.0, iva_amount=15.0)
        with self.assertRaises(UserError):
            self._render_invoice_xml(move)

    def test_reembolso_xml_buckets_06_07(self):
        """No-tax and exempt buckets render codes 6 and 7 with totals."""
        move = self._post_with_support(self._l10n_ec_create_in_invoice())
        self._add_reimbursement(move, no_tax_base=50.0, exempt_base=25.0)
        xml = self._render_invoice_xml(move)
        self.assertIn("<codigoPorcentaje>4</codigoPorcentaje>", xml)
        self.assertIn("<codigoPorcentaje>6</codigoPorcentaje>", xml)
        self.assertIn("<codigoPorcentaje>7</codigoPorcentaje>", xml)
        self.assertIn(
            "<totalBaseImponibleReembolso>175.00</totalBaseImponibleReembolso>", xml
        )
        self.assertIn("<totalImpuestoReembolso>15.00</totalImpuestoReembolso>", xml)

    # ------------------------------------------------------------------
    # ATS collector
    # ------------------------------------------------------------------

    def test_ats_row_carries_total(self):
        """The compras row carries totbasesImpReemb; own bases stay intact."""
        chart = self.env["account.chart.template"].with_company(self.company)
        tax_12 = chart.ref("tax_vat_510_sup_01")
        move = self._l10n_ec_create_in_invoice()
        move.invoice_line_ids.write(
            {"price_unit": 200.0, "tax_ids": [(6, 0, tax_12.ids)]}
        )
        self._post_with_support(move)
        self._add_reimbursement(move, base_amount=100.0)
        self._add_reimbursement(move, base_amount=50.0, sri_number="001-002-000000004")
        amounts = self.env["l10n.ec.ats.collector"]._l10n_ec_compras_amounts(move)
        self.assertEqual(amounts["totbasesImpReemb"], 150.0)
        self.assertEqual(amounts["baseImpGrav"], 200.0)

    def test_ats_row_without_legs_has_no_key(self):
        """Ordinary rows stay byte-identical: no key without legs."""
        move = self._l10n_ec_create_in_invoice()
        amounts = self.env["l10n.ec.ats.collector"]._l10n_ec_compras_amounts(move)
        self.assertNotIn("totbasesImpReemb", amounts)

    # ------------------------------------------------------------------
    # Views
    # ------------------------------------------------------------------

    def test_reimbursement_page_on_both_forms(self):
        """The tab composes exactly once into the bill and liquidation forms."""
        bill_arch = self.env["account.move"].get_view()["arch"]
        self.assertEqual(bill_arch.count('name="l10n_ec_reimbursement"'), 1)
        liquidation_view = self.env.ref(
            "l10n_ec_account_edi.account_invoice_liquidation_purchase_form_view"
        )
        liquidation_arch = self.env["account.move"].get_view(
            view_id=liquidation_view.id
        )["arch"]
        self.assertEqual(liquidation_arch.count('name="l10n_ec_reimbursement"'), 1)
