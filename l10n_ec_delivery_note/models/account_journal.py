from odoo import fields, models


class AccountJournal(models.Model):
    _inherit = "account.journal"

    # Odoo <= 18 shipped ``l10n_ec_emission_type`` in the core ``l10n_ec``
    # addon; it was dropped in 19.0 and neither ``l10n_ec_base`` nor
    # ``l10n_ec_account_edi`` reintroduced it. The delivery note emission rules
    # still need to tell a pre-printed journal apart from an electronic one, so
    # the field is restored here.
    # NOTE: if it lands in ``l10n_ec_base`` or ``l10n_ec_account_edi`` instead,
    # drop this definition - this module is loaded after both, so it would win.
    # The historical ``auto_printer`` value is intentionally not revived: it was
    # retired from the Ecuadorian legislation.
    l10n_ec_emission_type = fields.Selection(
        [
            ("pre_printed", "Pre Printed"),
            ("electronic", "Electronic"),
        ],
        string="Emission Type",
        default="electronic",
        help="Ecuador: whether the journal emits documents electronically.",
    )
