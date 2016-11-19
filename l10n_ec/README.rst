.. image:: https://img.shields.io/badge/licence-AGPL--3-blue.svg
   :target: http://www.gnu.org/licenses/agpl-3.0-standalone.html
   :alt: License: AGPL-3

=======================
Ecuador's Account Chart
=======================

This module adds the basic chart of account of Ecuador.
   * Works with the specifications of the Superintendencia de Compañías (SUPERCIAS).
   * It follows the requirements for SMEs.

Plan de cuentas para Ecuador
============================

Agrega el plan de cuentas para Ecuador.
   * Utiliza la clasificación de la Superintendencia de Compañías.
   * Sigue los requerimientos para las PYMEs

Installation
============

To install this module, you need to:
    * Delete the standard l10n_ec module from Odoo addons directory.
    * Copy this module on the same folder, replacing the deleted one.
    * Install this module, no need to install account first as this module will install and configure it properly.

Instalación
===========

Para instalar este módulo se debe:
    * Elimina el módulo l10n_ec de los addons de Odoo.
    * Copia este módulo en el mismo directorio, reemplazando el anterior.
    * Instalarlo de manera regular, no es necesario instalar account primero, este módulo lo instalará y configurará.

Configuration
=============

This module adds all the accounts as said by the Supercias but:
    * You should delete the accounts that don't apply to your company.
    * You should add the accounts that are not mandatory but you need.
    * As Odoo doesn't use total accounts, you need to use the correct coding to group your accounts correctly,
    for example, if you need a bank account, and put it inside 10101 account, you should code it as 10101xx.

Configuración
=============

Este módulo agrega las cuentas contables según la clasificación de la Supercias, sin embargo:
    * Es conveniente eliminar las cuentas contables que no vayan a ser utilizadas por su compañía.
    * Debe agregar las cuentas que no son obligatorias, pero desea utilizar.
    * Debido a que Odoo no usa cuentas de total, al crear una cuenta, tenga presente la codificación estándar,
    por ejemplo, si requiere una cuenta de bancos y colocarla dentro de 10101, su código debe ser 10101xx.

Demonstration in runbot
=======================

.. image:: https://odoo-community.org/website/image/ir.attachment/5784_f2813bd/datas
   :alt: Try me on Runbot
   :target: https://runbot.odoo-community.org/runbot/repo/github-com-oca-l10n-ecuador-212

Known issues / Roadmap
======================

    * The odoo default journals are been created in English and they also create their respective
    accounts, delete or edit them.
    * The default transfer account is 1010199, it's not part of Supercias's specification.
    * It's better if you remove the account 10101 and create new ones with codes 10101xx for your bank and cash accounts.

Problemas conocidos y planificación
===================================

    * Los diarios por defecto de odoo se crean en inglés y crean sus respectivas cuentas contables,
    es necesario editarlas o eliminarlas.
    * La cuenta de transferencias por defecto usada  es la 1010199, la cual no forma parte de la especificación de la Supercias.
    * Tendrá mejores resultados si elimina la cuenta 10101 y crea cuentas individuales con códigos 10101xx para las cuentas de bancos y efectivo.

Bug Tracker / Rastreo de Fallos
===============================

Los errores son rastreados en Github, en caso de problemas por favor revisa si ya han sido reportados en el apartado de issues,
si los has detectado primero, por favor reportalos con la informacion debida, al menos debes indicar la versión,
los pasos para reproducir y el comportamiento esperado.

Bugs are tracked on `GitHub Issues <https://github.com/OCA/l10n-ecuador/issues>`_.
In case of trouble, please check there if your issue has already been reported.
If you spotted it first, help us smashing it by providing a detailed and welcomed feedback
`here <https://github.com/OCA/l10n-ecuador/issues/new?body=module:%20l10n_ec%0Aversion:%209.0%0A%0A**Steps%20to%20reproduce**%0A-%20...%0A%0A**Current%20behavior**%0A%0A**Expected%20behavior**>`_.

Credits
=======

Images
------

* Odoo Community Association: `Icon <https://github.com/OCA/maintainer-tools/blob/master/template/module/static/description/icon.svg>`_.

Contributors
------------

    * Fábrica de Software Libre <desarrollo@libre.ec>
    * Daniel Alejandro Mendieta <damendieta@gmail.com>

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
