# CONFIGURACIÓNES AUTOMÁTICAS.

Para una correcta aplicación del plan de cuentas en Odoo V9, se ha requerido realizar las siguientes modificaciones al plan de cuentas publicado por la Superintendencia de Compañías.

    1. Solo se crean las cuentas de tipo "D" (detalle), las cuentas de tipo "T" (total) se implementan a través de reportes.
    2. La cuenta EFECTIVO Y EQUIVALENTES DEL EFECIVO se elimina puesto que por requerimientos de Odoo se crean las cuentas "EFECTIVO" y "BANCO", por lo que esta pasa a ser de tipo "T".
    3. Se agregan las cuentas pues son requeridas por Odoo:
        * Cash
        * Bank
        * Undistributed Profits/Losses
        * Transferencias (por defecto)
        
# CONFIGURACIONES MANUALES.

