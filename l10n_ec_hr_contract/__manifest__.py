{
    "name": "Manage Employee Contracts for Ecuador",
    "summary": "Contratos de empleados para Ecuador",
    "version": "19.0.1.0.0",
    "category": "Human Resources",
    "author": "Michael Telahun Makonnen, "
    "Cristian Salamea, "
    "Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/l10n-ecuador",
    "license": "AGPL-3",
    "depends": [
        "hr",
        "hr_holidays",
        "l10n_ec_hr_employee",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/hr_data.xml",
        "data/ir_cron_data.xml",
        "data/hr.contract.commision.csv",
        "data/hr.contract.branch.csv",
        "data/hr.contract.code.csv",
        "views/hr_contract_views.xml",
        "views/hr_contract_code_views.xml",
        "views/res_config_settings_views.xml",
    ],
    "installable": True,
}
