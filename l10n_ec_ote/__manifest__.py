# License AGPL-3 - See https://www.gnu.org/licenses/agpl-3.0.htm

{
    "name": "l10n_ec_ote",
    "summary": """Datos de provincias, cantones y parroquias de Ecuador.""",
    "version": "15.0.0.0.1",
    "author": "Fabrica de Software Libre,Odoo Community Association (OCA)",
    "license": "AGPL-3",
    "website": "https://github.com/OCA/l10n-ecuador",
    "category": "module_category_usability",
    "depends": ["base"],
    "data": [
        "views/res_partner.xml",
        "views/res_company.xml",
        "views/res_country.xml",
        "data/l10n_ec_ote.canton.csv",
        "data/l10n_ec_ote.parish.csv",
        "security/ir.model.access.csv",
    ],
    "pre_init_hook": "pre_install_hook",
}
