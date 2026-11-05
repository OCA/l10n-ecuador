"""Shared fixtures that post cleanly with and without the EDI chain.

The 104 collectors only need posted moves, but when the CI installs the
full chain (`l10n_ec_account_edi` + `l10n_ec_withhold` through the glue's
`test-requirements.txt`), posting validates more: the withhold module
requires a tax support on purchase bills, and the EDI format requires
partner/company VAT, a loaded certificate and a street on the emission
address for sales. These helpers set up exactly that in both worlds --
every field they touch exists without the chain, and the certificate
setup runs only when the chain is installed.
"""

try:
    from odoo.addons.l10n_ec_account_edi.tests.test_edi_common import (
        TestL10nECEdiCommon,
    )

    Base = TestL10nECEdiCommon
except ImportError:  # pragma: no cover - chain not installed
    from odoo.addons.account.tests.common import AccountTestInvoicingCommon

    Base = AccountTestInvoicingCommon

#: RUC proven valid by the ATS suite, reused so no digit check can fail.
RUC = "1713109678001"


def setup_edi_aware(cls, sale_journal=None, purchase_journal=None):
    """Make `partner_a` and the journals postable in both worlds."""
    ec = cls.env.ref("base.ec")
    cls.partner_a.write(
        {
            "vat": RUC,
            "country_id": ec.id,
            "l10n_latam_identification_type_id": (cls.env.ref("l10n_ec.ec_ruc").id),
        }
    )
    if hasattr(cls, "_setup_edi_company_ec"):
        cls()._setup_edi_company_ec()
    else:
        cls.company.partner_id.write({"vat": RUC})
    address = cls.env["res.partner"].create(
        {
            "name": "Emission address",
            "street": "Test street 123",
            "country_id": ec.id,
        }
    )
    for journal in (sale_journal, purchase_journal):
        if journal:
            journal.write(
                {
                    "l10n_ec_entity": "001",
                    "l10n_ec_emission": "001",
                    "l10n_ec_sri_payment_id": cls.env.ref("l10n_ec.P1").id,
                    "l10n_ec_emission_address_id": address.id,
                }
            )


def set_tax_support(move, code="01"):
    """Fill the withhold tax support when that module is installed.

    Presence-checked on posting by `l10n_ec_withhold`; the field does not
    exist without it, so this is a no-op in standalone runs.
    """
    if "l10n_ec_tax_support" in move._fields:
        move.l10n_ec_tax_support = code
