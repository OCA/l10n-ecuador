# -*- coding: utf-8 -*-
# © 2014 Savoir-faire Linux
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import models, fields, api

UPDATE_PARTNER_FIELDS = {
    'firstname',
    'lastname',
    'user_id',
    'address_home_id',
}


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    @api.model
    def split_name(self, name):
        clean_name = (name or '').split(None, 1)
        if not clean_name:
            return False, False
        return (clean_name[0], clean_name[1]) if len(clean_name) > 1 else (clean_name[0], False)

    def _auto_init(self):
        super()._auto_init()
        self._update_employee_names()

    @api.model
    def _update_employee_names(self):
        employees = self.search([
            '|', ('firstname', '=', ' '), ('lastname', '=', ' ')
        ])
        for ee in employees:
            lastname, firstname = self.split_name(ee.name)
            ee.write({
                'firstname': firstname,
                'lastname': lastname,
            })

    @api.model
    def _get_name(self, lastname, firstname):
        parts = [p for p in [lastname, firstname] if p and p.strip()]
        return ' '.join(parts)

    @api.onchange('firstname', 'lastname')
    def get_name(self):
        if self.firstname and self.lastname:
            self.name = self._get_name(self.lastname, self.firstname)

    def _firstname_default(self):
        return ' ' if self.env.context.get('module') else False

    firstname = fields.Char(
        string='Firstname',
        default=_firstname_default,
    )
    lastname = fields.Char(
        string='Lastname',
        required=True,
        default=_firstname_default,
    )
    identification_id = fields.Char(size=10)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('firstname') and vals.get('lastname'):
                vals['name'] = self._get_name(vals['lastname'], vals['firstname'])
            elif vals.get('name'):
                ln, fn = self.split_name(vals['name'])
                vals['lastname'] = ln or ' '
                vals['firstname'] = fn or ' '
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('firstname') or vals.get('lastname'):
            for record in self:
                lastname = vals.get('lastname') or record.lastname or ' '
                firstname = vals.get('firstname') or record.firstname or ' '
                vals['name'] = self._get_name(lastname, firstname)
        elif vals.get('name'):
            ln, fn = self.split_name(vals['name'])
            vals['lastname'] = ln
            vals['firstname'] = fn
        return super().write(vals)