# -*- coding: utf-8 -*-
from openerp import models, fields, api

class AccountInvoice(models.Model):
    _inherit = ['account.invoice']
    
    date = fields.Date(string='Accounting Date',
        readonly=False)

    month = fields.Char(string='Month',
                       compute="_compute_month",
                       store=True)

    year = fields.Char(string='Year',
                       compute="_compute_year",
                       store=True)

    @api.one
    @api.depends('date_invoice')
    def _compute_month(self):
        if self.date_invoice != False:
            self.month = str(self.date_invoice)[5:7]
            
    @api.one
    @api.depends('date_invoice')
    def _compute_year(self):
        if self.date_invoice != False:
            self.year = str(self.date_invoice)[0:4]