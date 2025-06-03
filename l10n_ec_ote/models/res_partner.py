from odoo import fields, models,api


class ResPartner(models.Model):
    _inherit = "res.partner"

    l10n_ec_parish_id = fields.Many2one(
        "l10n.ec.parish",
        ondelete="restrict",
        string="Parish",
    )
    
    city_id = fields.Many2one(
        "res.city",
        ondelete="restrict",
        string="Ciudad",
    )
    
    @api.onchange('state_id')
    def _onchange_state_id(self):
        """Clear city and parish when state changes"""
        if self.state_id:
            self.city_id = False
            self.l10n_ec_parish_id = False
    
    
  
    
    
