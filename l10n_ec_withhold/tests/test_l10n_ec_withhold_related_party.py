from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.l10n_ec_account_edi.tests.test_edi_common import TestL10nECEdiCommon


@tagged("post_install_l10n", "post_install", "-at_install")
class TestL10nWithholdRelatedParty(TestL10nECEdiCommon):
    @classmethod
    @AccountTestInvoicingCommon.setup_country("ec")
    @AccountTestInvoicingCommon.setup_chart_template("ec")
    def setUpClass(cls):
        super().setUpClass()
        cls.chart_template = cls.env["account.chart.template"].with_company(cls.company)
        cls.journal_purchase_withhold = cls.chart_template.ref("purchase_withhold_ec")
        cls.journal_purchase_withhold.l10n_ec_emission_address_id = (
            cls.partner_contact.id
        )

    def _create_ruc_partner(self, name, vat, related_party=False):
        return self.Partner.create(
            {
                "name": name,
                "vat": vat,
                "l10n_latam_identification_type_id": self.env.ref("l10n_ec.ec_ruc").id,
                "country_id": self.env.ref("base.ec").id,
                "l10n_ec_related_party": related_party,
            }
        )

    def _create_partner_withhold_edi_document(self, partner):
        """Return the EDI document of a purchase withhold issued to ``partner``.

        Mirrors the vals the purchase withhold wizard builds in
        ``_prepare_withholding_vals()`` without going through the wizard: the
        ``parteRel`` assertion lives in the document header, so no withholding
        tax line is needed. The basis/counterpart pair below exists only to
        satisfy the balance and post rules.
        """
        self._setup_edi_company_ec()
        withhold = self.AccountMove.create(
            {
                "journal_id": self.journal_purchase_withhold.id,
                "date": self.current_date,
                "move_type": "entry",
                "partner_id": partner.id,
                "ref": self.get_sequence_number(),
                "l10n_latam_document_type_id": self.env.ref("l10n_ec.ec_dt_07").id,
                "l10n_ec_withholding_type": "purchase",
                "line_ids": [
                    (
                        0,
                        0,
                        {
                            "partner_id": partner.id,
                            "account_id": self.company_data[
                                "default_account_expense"
                            ].id,
                            "name": "Withhold basis",
                            "debit": 100.0,
                            "credit": 0.0,
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "partner_id": partner.id,
                            "account_id": partner.property_account_payable_id.id,
                            "name": "Withhold counterpart",
                            "debit": 0.0,
                            "credit": 100.0,
                        },
                    ),
                ],
            }
        )
        withhold._post()
        return withhold._get_edi_document(self.edi_format)

    def test_01_l10n_ec_related_party_defaults_to_false(self):
        """The assertion field starts unset, never preselected."""
        partner = self._create_ruc_partner("Test Partner Unrelated", "1313109678002")
        self.assertFalse(partner.l10n_ec_related_party)

    def test_02_l10n_ec_parte_rel_is_no_when_unset(self):
        edi_doc = self._create_partner_withhold_edi_document(self.partner_ruc)
        self.assertFalse(self.partner_ruc.l10n_ec_related_party)
        self.assertEqual(edi_doc._l10n_ec_get_info_withhold()["parteRel"], "NO")

    def test_03_l10n_ec_parte_rel_is_si_when_related_party(self):
        self.partner_ruc.l10n_ec_related_party = True
        edi_doc = self._create_partner_withhold_edi_document(self.partner_ruc)
        self.assertEqual(edi_doc._l10n_ec_get_info_withhold()["parteRel"], "SI")

    def test_04_l10n_ec_related_party_is_per_partner(self):
        """Asserting SI for one partner must not change another's withhold."""
        partner = self._create_ruc_partner(
            "Test Partner Related", "1313109678003", related_party=True
        )
        related_doc = self._create_partner_withhold_edi_document(partner)
        unrelated_doc = self._create_partner_withhold_edi_document(self.partner_ruc)
        self.assertEqual(related_doc._l10n_ec_get_info_withhold()["parteRel"], "SI")
        self.assertEqual(unrelated_doc._l10n_ec_get_info_withhold()["parteRel"], "NO")

    def test_05_l10n_ec_parte_rel_reaches_the_rendered_xml(self):
        """Close the loop field -> ``_l10n_ec_get_info_withhold`` -> XML.

        The builder asserts the dict key; this asserts the ``parteRel`` element
        the SRI actually reads, so a renamed key or a template drift cannot
        pass silently. ``SI`` and ``NO`` are the only values the XSD simpleType
        ``parteRel`` accepts.
        """
        self.partner_ruc.l10n_ec_related_party = True
        related_doc = self._create_partner_withhold_edi_document(self.partner_ruc)
        self.assertIn("<parteRel>SI</parteRel>", related_doc._l10n_ec_render_xml_edi())
        self.partner_ruc.l10n_ec_related_party = False
        unrelated_doc = self._create_partner_withhold_edi_document(self.partner_ruc)
        self.assertIn(
            "<parteRel>NO</parteRel>", unrelated_doc._l10n_ec_render_xml_edi()
        )
