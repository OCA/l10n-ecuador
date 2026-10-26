from odoo import models


class UomUom(models.Model):
    _inherit = "uom.uom"

    def _uom_root_id(self):
        """Return the unit this one is ultimately relative to.

        Odoo 19 dropped ``uom.uom.category_id``: units are now a tree through
        ``relative_uom_id`` and the root of that tree is what plays the role of
        the former category, it is what makes two units comparable.
        """
        root = self
        while root.relative_uom_id:
            root = root.relative_uom_id
        return root
