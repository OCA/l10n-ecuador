# -*- coding: utf-8 -*-
from openerp import models, fields


class Identificacion(models.Model):
    _name = 'l10n_ec_sri_ats.identificacion'

    name = fields.Char('Tipo de identificacion')
    code = fields.Char('Código', size=2)
    active = fields.Boolean('Activo')
    description = fields.Char('Descripción')
    tpidprov = fields.Char('Código en compras', size=2)
    tpidcliente = fields.Char('Código en ventas', size=2)
