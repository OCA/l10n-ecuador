import setuptools

with open('VERSION.txt', 'r') as f:
    version = f.read().strip()

setuptools.setup(
    name="odoo10-addons-oca-l10n-ecuador",
    description="Meta package for oca-l10n-ecuador Odoo addons",
    version=version,
    install_requires=[
        'odoo10-addon-l10n_ec',
        'odoo10-addon-l10n_ec_config',
        'odoo10-addon-l10n_ec_ote',
    ],
    classifiers=[
        'Programming Language :: Python',
        'Framework :: Odoo',
        'Framework :: Odoo :: 10.0',
    ]
)
