.. image:: https://img.shields.io/badge/licence-AGPL--3-blue.svg
   :target: http://www.gnu.org/licenses/agpl-3.0-standalone.html
   :alt: License: AGPL-3

=======================
Ecuador's Account Chart
=======================

This module adds the basic chart of account of Ecuador.
    * Works with the specifications of the Superintendencia de Compañías.

Plan de Cuentas NIIF Pymes para Ecuador
=======================================

Agrega el plan de cuentas para Ecuador.
    * Utiliza la clasificación de la Superintendencia de Compañías.

Installation
============

To install this module, you need to:

* Add the module to your addons path.
* Install the module as usual.

Instalación
===========

Para instalar este módulo se debe:

* Agregar el módulo al directorio de addons.
* Instalarlo de manera regular.

Configuration
=============

This module adds all the accounts as said by the Supercias but:
    * You should delete the accounts that don't apply to your company.
    * You should add the accounts that are not mandatory but you need.
    * Keen in mind that you should use the standar coding, if you don't reports will fail.

Configuración
=============

Este módulo agrega las cuentas contables según la clasificación de la Supercias, sin embargo:
    * Es conveniente eliminar las cuentas contables que no vayan a ser utilizadas por su compañía.
    * Debe agregar las cuentas que no son obligatorias, pero desea utilizar.
    * Al crear una cuenta, tenga presente la codificación estándar, si no lo hace, los reportes fallarán.

Usage
=====

This module doesn't have any special usage guide lines. 

Instrucciones de uso
====================

Este módulo no requiere un uso especial.

Demostración en runbot
======================

.. image:: https://odoo-community.org/website/image/ir.attachment/5784_f2813bd/datas
   :alt: Try me on Runbot
   :target: https://runbot.odoo-community.org/runbot/repo/github-com-oca-l10n-ecuador-212

Known issues / Roadmap
======================

* The odoo default journals are been createn in English and they also create their respective
    accounts, delete or edit them.
* The default transfer account is 10101, please change it.
* You can use the account 10101 to map all your cash and bank accounts, or delete it and
    create other with codes 10101xx

Problemas conocidos y planificación
===================================

* Los diarios por defecto de odoo se crean en inglés y crean sus respectivas cuentas contables
    es necesario editarlas o eliminarlas.
* La cuenta de transferencias por defecto usada  es la 10101, debes cambiarla.
* Se puede usar la cuenta 10101 en todos los diarios de caja y bancos, o se la debe eliminar
    y crear cuentas individuales con códigos 10101xx

Bug Tracker
===========

Bugs are tracked on `GitHub Issues <https://github.com/OCA/l10n-ecuador/issues>`_.
In case of trouble, please check there if your issue has already been reported.
If you spotted it first, help us smashing it by providing a detailed and welcomed feedback
`here <https://github.com/OCA/l10n-ecuador/issues/new?body=module:%20l10n_ec_femd%0Aversion:%209.0%0A%0A**Steps%20to%20reproduce**%0A-%20...%0A%0A**Current%20behavior**%0A%0A**Expected%20behavior**>`_.

Rastreo de fallos
==================

Los fallos reciben seguimiento en `GitHub Issues <https://github.com/OCA/l10n-ecuador/issues>`_.
Si tiene algún inconveniente, por favor, revise si el mismo ha sido reportado con anterioridad.
Si no es así, su ayuda reportando el inconveniente será apreciada, por favor, sea lo más explícito posible
`aquí <https://github.com/OCA/l10n-ecuador/issues/new?body=module:%2020l10n_ec_femd%0Aversion:%209.0%0A%0A**Pasos%20para%20reproducir**%0A-%20...%0A%0A**Comportamiento%20actual**%0A%0A**Comportamiento%20esperado**>`_.

Credits
=======

Images
------

* Odoo Community Association: `Icon <https://github.com/OCA/maintainer-tools/blob/master/template/module/static/description/icon.svg>`_.

Contributors
------------

* Fábrica de Software Libre <desarrollo@libre.ec>

Maintainer
----------

.. image:: https://odoo-community.org/logo.png
   :alt: Odoo Community Association
   :target: https://odoo-community.org

This module is maintained by the OCA.

OCA, or the Odoo Community Association, is a nonprofit organization whose
mission is to support the collaborative development of Odoo features and
promote its widespread use.

To contribute to this module, please visit http://odoo-community.org... image:: https://img.shields.io/badge/licence-AGPL--3-blue.svg
    :alt: License: AGPL-3
