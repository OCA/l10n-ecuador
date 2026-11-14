from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.l10n_ec_account_edi.tests.test_edi_common import TestL10nECEdiCommon
from odoo.addons.l10n_ec_withhold.models.data import TAX_SUPPORT

# ``Tabla 5`` codes added late by the SRI, read from ``Catalogo_ATS.xls`` /
# ``TABLAS REFERENCIALES``: ``14`` since 2018-01-01 and ``15`` since
# 2020-06-01. The ``TAX_SUPPORT`` literal now lists ``00``-``15``, so a
# ``Selection`` fed by it can express the current era while still refusing
# typos at the ORM level. Catalogue-side validation for the reported period
# remains ``l10n_ec_ats``'s job.
TABLA_5_LATE_CODES = ("14", "15")


@tagged("post_install_l10n", "post_install", "-at_install")
class TestL10nEcTaxSupport(TestL10nECEdiCommon):
    """``l10n_ec_tax_support`` stays a ``Selection``.

    Per review, a free-text ``Char`` would let a user type an invalid code. A
    ``Selection`` built from ``TAX_SUPPORT`` (now ``00``-``15``) keeps the
    dropdown searchable as a many2one in V19 while refusing unknown codes.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.WizardWithhold = cls.env["l10n_ec.wizard.create.purchase.withhold"]
        cls.position_require_withhold = cls.env["account.fiscal.position"].create(
            {"name": "Withhold", "l10n_ec_avoid_withhold": False}
        )

    def test_01_move_tax_support_is_a_selection(self):
        """The move-level field is a dropdown fed by ``TAX_SUPPORT``."""
        field = self.env["account.move"]._fields["l10n_ec_tax_support"]
        self.assertEqual(field.type, "selection")
        codes = dict(field.selection)
        for code, _label in TAX_SUPPORT:
            self.assertIn(code, codes)
        for code in TABLA_5_LATE_CODES:
            self.assertIn(code, codes)

    def test_02_partner_tax_support_is_a_selection(self):
        field = self.env["res.partner"]._fields["l10n_ec_tax_support"]
        self.assertEqual(field.type, "selection")
        codes = dict(field.selection)
        for code in TABLA_5_LATE_CODES:
            self.assertIn(code, codes)

    def test_03_move_accepts_late_tabla_5_codes_and_refuses_unknown_ones(self):
        """``14``/``15`` are assignable; ``99`` is refused by the ORM."""
        move = self._l10n_ec_create_in_invoice(self.partner_ruc, auto_post=False)
        for code in TABLA_5_LATE_CODES:
            move.l10n_ec_tax_support = code
            self.assertEqual(move.l10n_ec_tax_support, code)
        with self.assertRaises(ValueError):
            move.l10n_ec_tax_support = "99"

    def test_04_partner_seeds_the_move(self):
        """The partner-level selection still seeds the move."""
        self.partner_ruc.l10n_ec_tax_support = "14"
        self.assertEqual(self.partner_ruc.l10n_ec_tax_support, "14")
        move = self._l10n_ec_create_in_invoice(self.partner_ruc, auto_post=False)
        move.l10n_ec_tax_support = False
        self.assertEqual(move._get_l10n_ec_tax_support(), "14")

    def test_05_withhold_line_keeps_its_selection_and_lists_the_two_codes(self):
        """The wizard's dropdown still resolves, including ``14``/``15``."""
        line_model = self.WizardWithhold._fields["withhold_line_ids"].comodel_name
        line_field = self.env[line_model]._fields["l10n_ec_tax_support"]
        self.assertEqual(line_field.type, "selection")
        labels = dict(getattr(line_field, "selection", []))
        for code in TABLA_5_LATE_CODES:
            self.assertIn(code, labels)
            self.assertTrue(labels[code].startswith(f"{code} - "), labels[code])

    def test_06_posting_still_refuses_a_purchase_document_without_support(self):
        """The guard fires when neither move nor lines carry a support."""
        invoice = self._l10n_ec_create_in_invoice(self.partner_ruc, auto_post=False)
        invoice.fiscal_position_id = self.position_require_withhold
        invoice.l10n_ec_tax_support = False
        invoice.invoice_line_ids.l10n_ec_tax_support = False
        with self.assertRaisesRegex(UserError, "Please fill a Tax Support"):
            invoice.action_post()
