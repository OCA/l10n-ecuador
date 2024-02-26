from odoo.addons.l10n_ec_account_edi.tests.test_common import (
    TestL10nECCommon,
)

# monkey patch for avoid errors on test because l10n_ec_tax_support is empty
original_l10n_ec_create_form_move = TestL10nECCommon._l10n_ec_create_form_move


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
    new_move_form = original_l10n_ec_create_form_move(
        self,
        move_type,
        internal_type,
        partner,
        taxes,
        products,
        journal,
        latam_document_type,
        use_payment_term,
        form_id,
    )
    if move_type == "in_invoice" and not new_move_form.l10n_ec_tax_support:
        new_move_form.l10n_ec_tax_support = "01"
    return new_move_form


TestL10nECCommon._l10n_ec_create_form_move = _l10n_ec_create_form_move
