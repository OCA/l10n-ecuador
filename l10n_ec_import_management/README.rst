=====================================================
Ecuador - Import Management (Gestión de Importaciones)
=====================================================

Módulo único para la empresa **importadora**. Fusiona la logística del antiguo
``freight_management_system`` (Cybrosys) con la liquidación aduanera de
``l10n_ec_import_costs``.

Flujo
=====

1. **Embarque** (*Imports > Operations > Shipments*): proveedor, órdenes de
   compra, Incoterm, forwarder, naviera, agente de aduana, puertos, BL/AWB,
   ETD/ETA, contenedores y documentos de soporte.
2. **Tracking**: botones *Departed* / *Arrived* o eventos manuales; cada evento
   queda en el chatter.
3. Al recibir la mercadería, **Create Customs Declaration** crea la
   liquidación (DAI) con las recepciones terminadas del embarque.
4. **Liquidación**: gastos de importación (flete, seguro y otros, en cualquier
   moneda, convertidos a la fecha de llegada), cálculo FOB → CIF, Ad Valorem,
   FODINFA, ICE, IVA y exoneraciones; datos de despacho (régimen, canal de
   aforo, levante, revisiones).
5. **Publicar** y generar la factura de aduana en borrador y el costo en
   destino. Cada tributo se asigna solo al producto que lo causa; los otros
   gastos marcados *Add to Stock* se reparten por valor.

Modelos
=======

==================================== ==========================================
Modelo                               Reemplaza a (freight / import_costs)
==================================== ==========================================
``l10n_ec.import.shipment``          ``freight.order``
``l10n_ec.import.shipment.container`` ``freight.order.line``
``l10n_ec.import.shipment.event``    ``freight.track`` / ``freight.order.track``
``l10n_ec.import.document``          ``custom.clearance.line``
``l10n_ec.import.port``              ``freight.port``
``l10n_ec.import.container.type``    ``freight.container``
``l10n_ec.import``                   ``l10n_ec.import`` + ``custom.clearance``
``l10n_ec.import.revision``          ``clearance.revision``
``l10n_ec.import.cost``              (nuevo)
==================================== ==========================================

Se eliminaron rutas, tarifario y servicios de venta (``freight.routes``,
``freight.price``, ``freight.service``) y la factura de venta al embarcador,
propios de un agente de carga.

Notas técnicas (Odoo 19)
========================

* ``stock.landed.cost.lines.l10n_ec_product_ids`` limita una línea de costo a
  ciertos productos (Odoo 19 no trae ``apply_on_product_ids``).
* Seguridad: compras (usuario/gerente), contabilidad (lectura) e inventario
  (lectura de embarques).

Herramienta de cálculo: compare siempre con la liquidación aduanera. No se
conecta con ECUAPASS/SENAE.
