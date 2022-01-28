import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = "res.partner"

    tradename = fields.Char(
        size=300,
    )

    @api.model
    def name_search(self, name="", args=None, operator="ilike", limit=100):
        args = args or []
        try:
            recs = self.search(
                [
                    "|",
                    "|",
                    ("tradename", operator, name),
                    ("name", operator, name),
                    ("vat", operator, name),
                ]
                + args,
                limit=limit,
            )
        except Exception:
            _logger.debug("falling back to basic search", exc_info=1)
            recs = self.search(
                ["|", ("tradename", operator, name), ("name", operator, name)] + args,
                limit=limit,
            )

        return recs.name_get()
