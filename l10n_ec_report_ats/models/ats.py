# -*- coding: utf-8 -*-

try:
    import xml.etree.cElementTree as ET
except ImportError:
    import xml.etree.ElementTree as ET

import base64
from openerp import models, fields, api, exceptions, SUPERUSER_ID
from datetime import datetime

class Ats(models.Model):
    _name = "l10n_ec_report_ats_16.ats"
    _description = "ATS"
    
    name = fields.Char('Anexo')

    # Definir el mes por defecto del reporte
    def _default_month(self):
        month = fields.datetime.now().strftime("%m")
        if month == '01':
            default = '12'
        else:
            default = str(int(month) - 1).zfill(2)
        return default

    month = fields.Selection([('01','Enero'),
                              ('02','Febrero'),
                              ('03','Marzo'),
                              ('04','Abril'),
                              ('05','Mayo'),
                              ('06','Junio'),
                              ('07','Julio'),
                              ('08','Agosto'),
                              ('09','Septiembre'),
                              ('10','Octubre'),
                              ('11','Noviembre'),
                              ('12','Diciembre')
                              ],
                                string='Mes',
                                default=_default_month,
                                required=True)

    # Definir el año por defecto del reporte
    def _default_year(self):
        month = fields.datetime.now().strftime("%m")
        year = fields.datetime.now().strftime("%Y")
        if month == '01':
            default = str(int(year) - 1)
        else:
            default = str(year)
        return default

    year = fields.Selection([('2015','2015'),
                             ('2016','2016'),
                             ('2017','2017'),
                              ],
                                string='Año',
                                default=_default_year,
                                required=True)
    file_save = fields.Binary('Archivo XML', readonly=True)
    state = fields.Selection([('borrador', 'Borrador'),
                              ('anulado', 'Anulado'),
                              ('presentado', 'Presentado')
                              ],
                                string="Estado",
                                default="borrador")

    @api.one
    def create_xml(self):
        
        # Datos
        year = self.year
        month = self.month
        company = self.env.user.company_id
        fiscal = company.partner_id.property_account_position_id
        
        # XML
        iva = ET.Element('iva')
        
        # Información del contribuyente
        ET.SubElement(iva, 'TipoIDInformante').text = fiscal.identificacion_id.code
        ET.SubElement(iva, 'razonSocial').text = company.name
        ET.SubElement(iva, 'Anio').text = year
        ET.SubElement(iva, 'Mes').text = month
        ET.SubElement(iva, 'numEstabRuc').text = company.establecimientos
        ET.SubElement(iva, 'totalVentas').text = 'DUMMIE'
        ET.SubElement(iva, 'codigoOperativo').text = 'IVA'
        
        #Compras
        compras = ET.SubElement(iva, 'compras')
        
        # lineas de factura
        line_compras = self.env['account.invoice.line'].search([['invoice_id.type', '=', 'in_invoice'], ['invoice_id.state', 'in', ('open','paid')], ['invoice_id.year', '=', year], ['invoice_id.month', '=', month]])




        for line in line_compras:

            detalleCompras = ET.SubElement(compras,"detalleCompras")

            codsustento = line.sustento_id.code
            codSustento = ET.SubElement(detalleCompras,"codSustento")
            codSustento.text = codsustento

            tpidprov = line.partner_id.name
            tpIdProv = ET.SubElement(detalleCompras,"tpIdProv")
            tpIdProv.text = tpidprov

            idprov = line.partner_id.vat
            idProv = ET.SubElement(detalleCompras,"idProv")
            idProv.text = idprov
        
        #Archivo
        data_file = ET.tostring(iva, encoding='UTF-8', method='xml')
        
        # Guardar el archivo y cambiar la información del informe
        self.write({'name': 'ATS-%s-%s.xml' % (month, year),
                    'file_save': base64.encodestring(data_file),
                    'state': 'borrador'})