# from odoo import models, fields, api


# class l10n_ec_ote(models.Model):
#     _name = 'l10n_ec_ote.l10n_ec_ote'
#     _description = 'l10n_ec_ote.l10n_ec_ote'

#     name = fields.Char()
#     value = fields.Integer()
#     value2 = fields.Float(compute="_value_pc", store=True)
#     description = fields.Text()
#
#     @api.depends('value')
#     def _value_pc(self):
#         for record in self:
#             record.value2 = float(record.value) / 100
