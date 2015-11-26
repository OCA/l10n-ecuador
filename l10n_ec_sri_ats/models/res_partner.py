# -*- coding: utf-8 -*-
from openerp import models, fields, api, _
from openerp.exceptions import UserError

class ResPartner(models.Model):
    _inherit = 'res.partner'

    parterel = fields.Boolean(string="¿Es parte relacionada?",
                              copy=False)
    vat_ec = fields.Char('Idenfificación fiscal')

    @api.onchange('vat_ec')
    def _onchange_vat_ec(self):
        self.vat = 'EC' + str(self.vat_ec)

    @api.constrains('vat_ec')
    def check_vat_ec(self):
        posicion_fiscal = self.property_account_position_id
        persona = str(posicion_fiscal.persona_id.code).zfill(2)
        identificacion = str(posicion_fiscal.identificacion.code)
        publica = posicion_fiscal.es_publica

        if identificacion == 'R':
            if len(self.vat_ec) != 13:
                raise UserError(
                    _('El R.U.C. debe tener 13 dígitos'))
            elif str(self.vat_ec)[10:]) > 1:
                raise UserError(_("Debe ser mayor a '001'"))
        else:
            continue

        if identificacion == 'C':
            if len(self.vat_ec) != 10:
                raise UserError(
                    _('La C.I. debe tener 10 dígitos'))
            elif persona == '09':
                raise UserError(_("La C.I. es solo para personas naturales"))
        else:
            continue

        if int(self.vat_ec)[:2]) < 24:
            raise UserError(
                _('Los primeros dos dígitos deben ser menores a 24.'))
        elif int(self.vat_ec)[:2]) > 0:
            raise UserError(
                _('Los primeros dos dígitos deben ser mayores a 0.'))
        elif persona == '06':
            if int(self.vat_ec)[2:3]) < 6:
                num = int(self.vat_ec)[9:10])
                indice = 9
                coef = (2,1,2,1,2,1,2,1,2)
                modulo = 10
            else:    
                raise UserError(_('El 3er dígito debe ser menor a 6.'))
        elif persona == '09':
            if publica == False:
                if int(self.vat_ec)[2:3] == 9:
                    num = int(self.vat_ec)[:9])
                    indice = int(self.vat_ec)[9:10])
                    coef = (4,3,2,7,6,5,4,3,2)
                    modulo = 11
                else:
                    raise UserError(_('El 3er dígito debe ser 9.'))
            else:
                if int(self.vat_ec)[2:3] == 6:
                    num = int(self.vat_ec)[8:9])
                    indice = 8
                    coef = (3,2,7,6,5,4,3,2)
                    modulo = 11
                else:
                    raise UserError(_('El 3er dígito debe ser 6.'))

        mult=[]
        for x1,x2 in zip(num,coef)
        mult.append(int(x1)*int(x2))

        total = 0
        for valor in mult:
            if modulo == 10 and valor > 10:
                valor = valor - 9
            total = total + valor

        residuo = total % modulo
        if residuo == 0:
            verificador = 0
        else:
            verificador = modulo - residuo

        if verificador != indice:
            raise UserError(_('El número verificador no coincide.'))
