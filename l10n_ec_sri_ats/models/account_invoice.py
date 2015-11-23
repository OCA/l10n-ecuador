# -*- coding: utf-8 -*-
from openerp import models, fields


class AccountInvoice(models.Model):
    _inherit = ['account.invoice']

    comprobante_id = fields.Many2one('l10n_ec_sri_ats.comprobante',
                                      string='Tipo de comprobante')
    autorizacion_id = fields.Many2one('l10n_ec_sri_ats.autorizacion',
                                      string='Autorización')
    detercero_id = fields.Many2one('l10n_ec_sri_ats.detercero',
                                   string='Autorización')
    numero_comprobante = fields.Char(string='Número', size=18)
    ret_autorizacion_id = fields.Many2one('l10n_ec_sri_ats.autorizacion',
                                      string='Autorización')
    ret_detercero_id = fields.Many2one('l10n_ec_sri_ats.detercero',
                                   string='Autorización')
    numero_retencion = fields.Char(string='Número', size=18)

    @api.onchange('autorizacion_id')
    def _onchange_autorizacion_id(self):
        self.numero_comprobante =
            (str(self.autorizacion_id.establecimiento) + "-" +
             str(self.autorizacion_id.punto_impresion) + "-00000000")

    @api.onchange('detercero_id')
    def _onchange_detercero_id(self):
        self.numero_comprobante =
            (str(self.detercero_id.establecimiento) + "-" + 
             str(self.detercero_id.punto_impresion) + "-00000000")

    @api.onchange('ret_autorizacion_id')
    def _onchange_ret_autorizacion_id(self):
        self.numero_retencion =
            (str(self.autorizacion_id.establecimiento) + "-" +
             str(self.autorizacion_id.punto_impresion) + "-00000000")

    @api.onchange('ret_detercero_id')
    def _onchange_ret_detercero_id(self):
        self.numero_retencion =
            (str(self.detercero_id.establecimiento) + "-" +
             str(self.detercero_id.punto_impresion) + "-00000000")
