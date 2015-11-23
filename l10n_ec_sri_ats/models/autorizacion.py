# -*- coding: utf-8 -*-
from openerp import models, fields, api


class Autorizacion(models.Model):
    _name = 'l10n_ec_sri_ats.autorizacion'
    _description = "Autorizaciones"

    name = fields.Char(
        string="Autorización", compute="_compute_name", store=False)
    numero = fields.Char(
        'Nro. de autorización', required=True)
    establecimiento = fields.Char(
        'Establecimiento', size=3, required=True)
    punto_impresion = fields.Char(
        'Punto de impresión', size=3, required=True)
    valido_desde = fields.Date(
        'Fecha de emisión',
        help="""Ingrese la fecha en la que la autorización
                fue emitida por parte del S.R.I.""")
    valido_hasta = fields.Date(
        'Fecha de expiración', required=True,
        help="""Ingrese la fecha en la que la autorización
                fue emitida por parte del S.R.I.""")
    lineaautorizacion_ids = fields.One2many(
        'l10n_ec_sri_ats.lineaautorizacion', inverse_name='autorizacion_id',
        ondelete='restrict', string="Comprobantes autorizados")
    invoice_ids = fields.One2many(
        'account.invoice', inverse_name='autorizacion_id',
        ondelete='restrict', string="Facturas")

    @api.multi
    @api.depends('punto_impresion', 'establecimiento', 'numero')
    def _compute_name(self):
        self.name = (str(self.establecimiento) + "-" +
                     str(self.punto_impresion) + "-" + str(self.numero))


class DeTercero(models.Model):
    _name = 'l10n_ec_sri_ats.detercero'
    _inherit = 'l10n_ec_sri_ats.autorizacion'
    _description = "Autorizaciones de terceros"

    partner_id = fields.Many2one(
        'res.partner', string='Cliente/Proveedor', readonly=False,
        default=(lambda self: self.env['account.invoice'].search([], limit=1).partner_id))
