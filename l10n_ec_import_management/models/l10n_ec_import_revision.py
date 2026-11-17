from odoo import api, fields, models


class L10nEcImportRevision(models.Model):
    """Corrections requested on a customs declaration (observations of the
    customs officer, substitute DAI...)."""

    _name = "l10n_ec.import.revision"
    _description = "Customs Declaration Revision"
    _order = "import_id, date desc, id desc"

    import_id = fields.Many2one("l10n_ec.import", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="import_id.company_id", store=True, index=True)
    date = fields.Date(required=True, default=fields.Date.context_today)
    reason = fields.Text(required=True)
    user_id = fields.Many2one("res.users", string="Responsible", default=lambda self: self.env.user)
    resolved = fields.Boolean()

    @api.model_create_multi
    def create(self, vals_list):
        revisions = super().create(vals_list)
        for revision in revisions:
            revision.import_id.message_post(body=self.env._("Customs revision: %s", revision.reason))
        return revisions
