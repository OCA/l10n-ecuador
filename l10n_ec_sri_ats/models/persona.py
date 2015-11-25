# -*- coding: utf-8 -*-
from openerp import models, fields


class Persona(models.Model):
    _name = 'l10n_ec_sri_ats.persona'

    name = fields.Char('Tipo de persona')
    code = fields.Char('Código', size=1)
    idprov = fields.Char('Tipo de identificación del Proveedor',
                         size=2)
