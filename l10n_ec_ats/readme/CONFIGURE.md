Nothing to configure.

The module installs the `l10n.ec.temporal` abstract mixin and requires
`l10n_ec_base`, `l10n_ec_account_edi` and `l10n_ec_withhold` to be installed.
It exposes no user interface and adds no technical setting.

Once the SRI catalogs land, each catalog entry will inherit the mixin and
expose `date_start` and `date_end` in its form view, with `date_end` left empty
for the entries that are still in force.