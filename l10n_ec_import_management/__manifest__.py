{
    "name": "Ecuador - Import Management (Embarques y Liquidación de Importaciones)",
    "summary": "Embarques (puertos, contenedores, tracking, documentos), despacho aduanero (DAI) "
    "y liquidación FOB/CIF, Ad Valorem, FODINFA, ICE e IVA con costo en destino",
    "description": """
Gestión de importaciones para Ecuador (empresa importadora)
===========================================================
Embarque (logística)
--------------------
* Embarque por proveedor con órdenes de compra, Incoterm, transporte
  (marítimo FCL/LCL, aéreo, terrestre FTL/LTL), puertos de carga y descarga,
  BL/AWB/carta de porte, ETD/ETA.
* Contenedores (tipo, número, sello, peso, volumen).
* Tracking del embarque con historial en el chatter.
* Documentos de soporte (BL, factura comercial, packing list, póliza,
  certificado de origen, documentos de control previo...).

Despacho aduanero y liquidación (DAI)
-------------------------------------
* Liquidación por DAI desde las recepciones terminadas del embarque.
* Agente de aduana, régimen, canal de aforo, fecha de levante y revisiones.
* Gastos de importación (flete, seguro y otros) por proveedor y moneda,
  convertidos a la fecha de llegada; el flete y el seguro alimentan el CIF.
* Subpartidas arancelarias con reglas mixtas; Ad Valorem, FODINFA, ICE e IVA
  por producto con exoneraciones justificadas.
* Costo en destino (landed cost) asignado al producto que causa cada tributo.
* Factura en borrador para la autoridad aduanera (IVA en su propia cuenta).
* Reportes PDF y exportación Excel.

Herramienta de cálculo: compare siempre con la liquidación aduanera.
No se conecta con ECUAPASS/SENAE.
""",
    "version": "19.0.1.0.0",
    "category": "Accounting/Localizations",
    "countries": ["ec"],
    "license": "AGPL-3",
    "author": "OCA , Leonarfo Gomez",
    "website": "https://github.com/OCA/l10n-ecuador",
    "depends": ["purchase_stock", "stock_landed_costs", "mail"],
    "external_dependencies": {"python": ["xlsxwriter"]},
    "data": [
        "security/l10n_ec_import_security.xml",
        "security/ir.model.access.csv",
        "data/ir_sequence_data.xml",
        "data/product_data.xml",
        "report/l10n_ec_import_report.xml",
        "report/l10n_ec_import_shipment_report.xml",
        "views/l10n_ec_import_tariff_views.xml",
        "views/l10n_ec_import_port_views.xml",
        "views/l10n_ec_import_container_type_views.xml",
        "views/l10n_ec_import_views.xml",
        "views/l10n_ec_import_shipment_views.xml",
        "views/product_template_views.xml",
        "views/res_config_settings_views.xml",
        "views/menus.xml",
    ],
    "installable": True,
    "application": True,
}
