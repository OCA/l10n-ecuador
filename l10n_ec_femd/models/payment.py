# -*- coding: utf-8 -*-
from openerp import models, fields


class Payment(models.Model):
    _inherit = 'account.payment'

    cobro_md = fields.Selection([
        ('95010101',
         'Ventas de bienes y prestación de servicios'),
        ('95010102',
         'Regalías, cuotas, comisiones y otras actividades ordinarias'),
        ('95010103',
         'Contratos mantenidos con propósitos de intermediación'),
        ('95010104',
         'Primas y prestaciones, anualidades y otros beneficios de pólizas'),
        ('95010105',
         'Otros cobros por actividades de operación'), ],
        string='Clasificación del cobro',
        default='95010101')

    pago_md = fields.Selection([
        ('95010201',
         'Proveedores por el suministro de bienes y servicios'),
        ('95010202',
         'Contratos mantenidos para intermediación o para negociar'),
        ('95010203',
         'Por cuenta de los empleados'),
        ('95010204',
         'Primas y prestaciones, anualidades y obligaciones de las pólizas'),
        ('95010205',
         'Otros pagos por actividades de operación'), ],
        string='Clasificación del pago',
        default='95010201')
