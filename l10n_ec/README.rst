.. image:: https://img.shields.io/badge/licence-AGPL--3-blue.svg
   :target: http://www.gnu.org/licenses/agpl-3.0-standalone.html
   :alt: License: AGPL-3

======================================================
Ecuador's Account Chart / Plan de Cuentas para Ecuador
======================================================

This module adds the basic chart of account of Ecuador.
* Works with the specifications of the Superintendencia de Compañías (SUPERCIAS).
* It follows the requirements for SMEs.

Agrega el plan de cuentas para Ecuador.
* Utiliza la clasificación de la Superintendencia de Compañías.
* Sigue los requerimientos para las PYMEs

Tested on version / Probado en la versión
=========================================
10.0-20161103

Installation / Instalación
==========================

To install this module, you need to:
* Delete the standard l10n_ec module from Odoo addons directory.
* Copy this module on the same folder, replacing the deleted one.
* Install this module, no need to install account first as this module will install and configure it properly.

Para instalar este módulo se debe:
* Elimina el módulo l10n_ec de los addons de Odoo.
* Copia este módulo en el mismo directorio, reemplazando el anterior.
* Instalarlo de manera regular, no es necesario instalar account primero, este módulo lo instalará y configurará.

Configuration / Configuración
=============================

This module adds all the accounts as said by the Supercias, some recommendations are:
* You should delete the accounts that don't apply to your company.
* You should add the accounts that are not mandatory but you need.
* As Odoo doesn't use total accounts, you need to use the correct coding to group your accounts correctly, for example, if you need a bank account, and put it inside 10101 account, you should code it as 10101xx.
* The account 10101 has been deleted as it's always better to use detail accounts for bank and cash journals, Odoo will create the accounts 000001 and 000002 for the default bank and cash journals, it's reccommended for you to change them to 1010101 and 1010102 or any other number you like, but you need to change the code.

Este módulo agrega las cuentas contables según la clasificación de la Supercias, sin embargo, te damos algunas recomendaciones:
* Es conveniente eliminar las cuentas contables que no vayan a ser utilizadas por su compañía.
* Debe agregar las cuentas que no son obligatorias, pero desea utilizar.
* Debido a que Odoo no usa cuentas de total, al crear una cuenta, tenga presente la codificación estándar, por ejemplo, si requiere una cuenta de bancos y colocarla dentro de 10101, su código debe ser 10101xx.
* La cuenta

Demonstration in runbot / Demostración en runbot
================================================

.. image:: https://odoo-community.org/website/image/ir.attachment/5784_f2813bd/datas
   :alt: Try me on Runbot
   :target: https://runbot.odoo-community.org/runbot/repo/github-com-oca-l10n-ecuador-212

Known issues / Problemas conocidos
==================================

* The default transfer account is 1010199, it's not part of Supercias's specification, but it's recommended so Odoo can use it to internal transfers, unless you know what are you doing, use it.
* This char of accounts doesn't include any tax configuration as it pretends to be compatible with any of the other localizations available.

* La cuenta de transferencias por defecto usada  es la 1010199, la cual no forma parte de la especificación de la Supercias, sin embargo, es necesaria para que Odoo pueda realizar las transferencias internas, a menos que sepas lo que haces, no cambies esta configuración.
* Este plan de cuentas no incluye información de impuestos debido a que pretende ser compatible con las demás localizaciónes ecuatorianas disponibles.

Roadmap / Planificación
=======================

* Default jornals are created in English and their sequences aren't the best for Ecuador, it's on our plans to change the standard Odoo journals.

* Los Diarios por defecto son creados en inglés y las secuencias no son las mejores para Ecuador, está en nuestros planes cambiar los Diarios por unos más apropiados.

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
