import setuptools

with open('VERSION.txt', 'r') as f:
    version = f.read().strip()

setuptools.setup(
    name="odoo-addons-oca-l10n-ecuador",
    description="Meta package for oca-l10n-ecuador Odoo addons",
    version=version,
    install_requires=[
        'odoo-addon-l10n_ec_account_edi>=15.0dev,<15.1dev',
        'odoo-addon-l10n_ec_base>=15.0dev,<15.1dev',
    ],
    classifiers=[
        'Programming Language :: Python',
        'Framework :: Odoo',
        'Framework :: Odoo :: 15.0',
    ]
)
