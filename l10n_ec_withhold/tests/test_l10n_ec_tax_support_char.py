from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.l10n_ec_account_edi.tests.test_edi_common import TestL10nECEdiCommon

# The two ``Tabla 5`` codes the Python label list was missing, read from
# ``Catalogo_ATS.xls`` / ``TABLAS REFERENCIALES`` and mirrored by
# ``l10n_ec_ats`` in ``data/ats_catalog_05.xml``. Both are in force today:
# ``14`` since 2018-01-01 and ``15`` since 2020-06-01. A ``Selection`` fed by a
# literal list cannot store a code the list forgot, which is the whole reason
# this field is a ``Char`` now.
TABLA_5_CODES_THE_LABEL_LIST_OMITTED = ("14", "15")


@tagged("post_install_l10n", "post_install", "-at_install")
class TestL10nEcTaxSupportChar(TestL10nECEdiCommon):
    """``l10n_ec_tax_support`` is a capture, not a closed list.

    The field used to be a ``Selection`` fed by the module-level ``TAX_SUPPORT``
    literal, so the codes a document could carry were capped at whatever that
    list happened to contain. ``Tabla 5`` is effective-dated and holds 16 codes,
    so a ``Char`` plus catalogue-side validation is the only shape that can
    express the current era. ``l10n_ec_ats`` owns that validation; this suite
    only pins the storage shape and proves the retype changed nothing else.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.WizardWithhold = cls.env["l10n_ec.wizard.create.purchase.withhold"]
        cls.position_require_withhold = cls.env["account.fiscal.position"].create(
            {"name": "Withhold", "l10n_ec_avoid_withhold": False}
        )

    def test_01_move_tax_support_is_a_two_character_char(self):
        """The move-level field is a capture: two characters, no code list."""
        field = self.env["account.move"]._fields["l10n_ec_tax_support"]
        self.assertEqual(field.type, "char")
        self.assertEqual(field.size, 2)
        self.assertIsNone(getattr(field, "selection", None))

    def test_02_partner_tax_support_is_a_two_character_char(self):
        field = self.env["res.partner"]._fields["l10n_ec_tax_support"]
        self.assertEqual(field.type, "char")
        self.assertEqual(field.size, 2)
        self.assertIsNone(getattr(field, "selection", None))

    def test_03_move_accepts_a_tabla_5_code_the_literal_list_omitted(self):
        """The end-to-end proof the retype was for.

        ``15`` is *Pagos efectuados por consumos propios y de terceros de
        servicios digitales*, in force since 2020-06-01. As a ``Selection`` it
        was not assignable at all.
        """
        move = self._l10n_ec_create_in_invoice(self.partner_ruc, auto_post=False)
        for code in TABLA_5_CODES_THE_LABEL_LIST_OMITTED:
            move.l10n_ec_tax_support = code
            self.assertEqual(move.l10n_ec_tax_support, code)
        # A code no ``Tabla 5`` row states is just as storable. Rejecting it is
        # ``l10n_ec_ats``'s job against the catalogue, never this field's.
        move.l10n_ec_tax_support = "99"
        self.assertEqual(move.l10n_ec_tax_support, "99")

    def test_04_partner_accepts_a_tabla_5_code_the_literal_list_omitted(self):
        """The partner-level capture is a ``Char`` too, and still seeds the move."""
        self.partner_ruc.l10n_ec_tax_support = "14"
        self.assertEqual(self.partner_ruc.l10n_ec_tax_support, "14")
        move = self._l10n_ec_create_in_invoice(self.partner_ruc, auto_post=False)
        move.l10n_ec_tax_support = False
        self.assertEqual(move._get_l10n_ec_tax_support(), "14")

    def test_05_withhold_line_keeps_its_selection_and_gained_the_two_codes(self):
        """The wizard's dropdown still resolves, and can express a current era.

        ``wizard_create_purchase_withhold.py`` builds its label map from the
        wizard *line* field's selection, so the retype on ``account.move`` does
        not disturb it. What it does need is that the literal behind it lists
        ``14`` and ``15``.
        """
        line_model = self.WizardWithhold._fields["withhold_line_ids"].comodel_name
        line_field = self.env[line_model]._fields["l10n_ec_tax_support"]
        self.assertEqual(line_field.type, "selection")
        labels = dict(getattr(line_field, "selection", []))
        for code in TABLA_5_CODES_THE_LABEL_LIST_OMITTED:
            self.assertIn(code, labels)
            self.assertTrue(labels[code].startswith(f"{code} - "), labels[code])

    def test_06_posting_still_refuses_a_purchase_document_without_support(self):
        """The retype must not weaken the guard.

        ``account.move._post`` refuses a purchase document that carries neither
        a move-level nor a line-level tax support. With ``Char`` an unset value
        is ``False`` exactly as it was with ``Selection``, so the guard fires on
        the same condition and raises the same ``UserError``.
        """
        invoice = self._l10n_ec_create_in_invoice(self.partner_ruc, auto_post=False)
        invoice.fiscal_position_id = self.position_require_withhold
        invoice.l10n_ec_tax_support = False
        invoice.invoice_line_ids.l10n_ec_tax_support = False
        with self.assertRaisesRegex(UserError, "Please fill a Tax Support"):
            invoice.action_post()
