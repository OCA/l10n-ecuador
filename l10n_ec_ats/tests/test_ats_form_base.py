"""Shared Form-visibility fixture for the ATS document-creating suites.

Why this exists: the customer/vendor invoice form declares ``journal_id``
with ``invisible="not show_journal"``, and core ``account`` computes
``show_journal = len(suitable_journal_ids) > 1 or ...`` (``account_move.py``).
``suitable_journal_ids`` is every journal of the matching type (``sale`` for
an ``out_invoice``, ``purchase`` for an ``in_invoice``) for the company, and
the EC localization narrows it further: ``l10n_ec_account_edi`` recomputes
suitable journals with an extra ``l10n_ec_is_purchase_liquidation`` match on
the form's ``internal_type`` context, so a plain vendor bill only sees
purchase journals that are *not* purchase liquidations. With a single
suitable journal the field is invisible, and Odoo 19's ``Form`` refuses to
write invisible fields, so the shared helper
``_l10n_ec_create_form_move`` (``l10n_ec_account_edi/tests/test_common.py``)
cannot set ``journal_id`` in a company with one journal per (type,
liquidation-flag) pair -- which is exactly what this environment seeds (one
``sale`` journal, and for plain bills only ``BILL`` once the ``LDP``
liquidation journal is filtered out).

A company with two emission points is ordinary, so the fixture declares the
second one explicitly: one extra ``sale`` journal and one extra plain
``purchase`` journal on the test company, copied from the defaults so they
inherit the company, the type and the establishment (``001``/``001`` or empty
-- never a new establishment, so ``numEstabRuc`` and the
establishment-keyed blocks are unaffected). They carry a high ``sequence`` so
the original journal stays the default, an explicit
``l10n_ec_is_purchase_liquidation = False`` so the EC filter keeps them
suitable, and unique codes (``ATS2``/``ATB2``) that no test below reuses.
"""

from odoo.addons.l10n_ec_account_edi.tests.test_edi_common import TestL10nECEdiCommon


class TestL10nEcAtsFormBase(TestL10nECEdiCommon):
    """Base for ATS suites that drive documents through the Form helper."""

    @classmethod
    def _ensure_multiple_suitable_journals(cls):
        """Guarantee more than one suitable journal per invoice type.

        Must run inside ``setUpClass`` after the default journals are
        configured: with two or more suitable journals ``show_journal`` is
        true and the shared Form helper can assign ``journal_id`` again.
        Each test class rolls its transaction back, so the copies never leak
        across classes.

        The counts are EC-aware on purpose: ``l10n_ec_account_edi`` keeps
        only journals whose ``l10n_ec_is_purchase_liquidation`` matches the
        form's ``internal_type`` context, so the plain-bill suitability of
        ``BILL`` + ``LDP`` is really just ``BILL``. Every fixture below
        drives ``internal_type='invoice'`` forms, hence the ``False`` flag.
        """
        Journal = cls.env["account.journal"]
        invoice_domain = [
            ("company_id", "=", cls.company.id),
            ("l10n_ec_is_purchase_liquidation", "=", False),
            ("active", "=", True),
        ]
        if len(Journal.search(invoice_domain + [("type", "=", "sale")])) <= 1:
            base = cls.company_data.get("default_journal_sale") or Journal.search(
                invoice_domain + [("type", "=", "sale")], limit=1
            )
            base.copy(
                {
                    "code": "ATS2",
                    "name": "ATS second sale journal",
                    "sequence": 100,
                    "l10n_ec_is_purchase_liquidation": False,
                }
            )
        if len(Journal.search(invoice_domain + [("type", "=", "purchase")])) <= 1:
            base = cls.company_data.get("default_journal_purchase") or Journal.search(
                invoice_domain + [("type", "=", "purchase")], limit=1
            )
            base.copy(
                {
                    "code": "ATB2",
                    "name": "ATS second purchase journal",
                    "sequence": 100,
                    "l10n_ec_is_purchase_liquidation": False,
                }
            )
