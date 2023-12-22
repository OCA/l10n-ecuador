import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.safe_eval import safe_eval

from .data import TAX_SUPPORT

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = "account.move"

    l10n_ec_withholding_type = fields.Selection(
        [
            ("purchase", "Purchase"),
            ("sale", "Sale"),
        ],
        string="Withholding Type",
    )
    l10n_ec_withhold_line_ids = fields.One2many(
        comodel_name="account.move.line",
        inverse_name="l10n_ec_withhold_id",
        string="Lineas de retencion",
        readonly=True,
    )
    l10n_ec_withhold_ids = fields.Many2many(
        "account.move",
        relation="l10n_ec_withhold_invoice_rel",
        column1="move_id",
        column2="withhold_id",
        string="Withhold",
        readonly=True,
        copy=False,
    )
    l10n_ec_withhold_count = fields.Integer(
        string="Withholds Count", compute="_compute_l10n_ec_withhold_count"
    )
    l10n_ec_withhold_active = fields.Boolean(
        string="Withholds?",
        compute="_compute_l10n_ec_withhold_active",
        store=True,
    )
    l10n_ec_tax_support = fields.Selection(
        TAX_SUPPORT, string="Tax Support", help="Tax support in invoice line"
    )

    @api.onchange("partner_id")
    def _onchange_partner_id(self):
        self.l10n_ec_tax_support = self._get_l10n_ec_tax_support()
        return super()._onchange_partner_id()

    @api.depends("l10n_ec_withhold_ids")
    def _compute_l10n_ec_withhold_count(self):
        for move in self:
            move.l10n_ec_withhold_count = len([x for x in move.l10n_ec_withhold_ids if x.state != "cancel"])

    @api.depends(
        "state",
        "fiscal_position_id",
        "company_id",
    )
    def _compute_l10n_ec_withhold_active(self):
        """
        Compute when the user can input withholding.
        By default, if the company is Ecuadorian and this module is installed,
        this feature is enabled.
        However, if withholding is explicitly configured
        as disabled in the tax position, then disable this feature.
        """
        for move in self:
            move_fiscal_position = move.fiscal_position_id
            company_fiscal_position = move.company_id.property_account_position_id
            if (
                move.state != "posted"
                or move.move_type
                not in [
                    "in_invoice",
                    "out_invoice",
                ]
                or move.tax_country_code != "EC"
            ):
                move.l10n_ec_withhold_active = False
                continue
            move.l10n_ec_withhold_active = True
            if (
                move.move_type == "out_invoice"
                and move_fiscal_position.l10n_ec_avoid_withhold
            ):
                move.l10n_ec_withhold_active = False
            if move.move_type == "in_invoice" and (
                move_fiscal_position.l10n_ec_avoid_withhold
                or company_fiscal_position.l10n_ec_avoid_withhold
            ):
                move.l10n_ec_withhold_active = False

    @api.constrains("l10n_ec_withholding_type")
    def _check_l10n_ec_sale_withholding_duplicity(self):
        for move in self:
            if not move.is_sale_withhold():
                continue
            other_withholdings = self.search_count(
                [
                    ("partner_id", "=", move.partner_id.id),
                    ("ref", "=", move.ref),
                    ("l10n_ec_withholding_type", "=", "sale"),
                    ("state", "=", "posted"),
                ]
            )
            if other_withholdings > 1:
                raise UserError(
                    _(
                        "You can't create other withholding with same Number: %s for Customer: %s",
                        move.ref,
                        move.partner_id.display_name,
                    )
                )

    def _post(self, soft=True):
        # OVERRIDE
        # Set the electronic document to be posted and post immediately for synchronous formats.
        # only for purchase withhold
        posted = super()._post(soft=soft)
        for move in posted:
            # check if tax support is set into any invoice line or invoice
            if move.is_purchase_document() and move.l10n_ec_withhold_active:
                lines_without_tax_support = any(
                    not invoice_line.l10n_ec_tax_support
                    for invoice_line in move.invoice_line_ids
                )
                if not move.l10n_ec_tax_support and lines_without_tax_support:
                    raise UserError(
                        _(
                            "Please fill a Tax Support on Invoice: %s or on all Invoice lines"
                        )
                        % (move.display_name)
                    )
        return posted

    def button_cancel(self):
        res = super().button_cancel()
        # cancel purchase withholding
        for move in self:
            for withhold in move.l10n_ec_withhold_ids:
                if withhold.is_purchase_withhold():
                    withhold.button_cancel()
        return res

    def action_send_and_print(self):
        if any(move.is_purchase_withhold() for move in self):
            template = self.env.ref(self._get_mail_template(), raise_if_not_found=False)
            return {
                "name": _("Send"),
                "type": "ir.actions.act_window",
                "view_type": "form",
                "view_mode": "form",
                "res_model": "account.move.send",
                "target": "new",
                "context": {
                    "active_ids": self.ids,
                    "default_mail_template_id": template.id,
                },
            }
        return super().action_send_and_print()

    @api.model
    def get_withhold_types(self):
        return ["purchase", "sale"]

    def is_withhold(self):
        return (
            self.tax_country_code == "EC"
            and self.l10n_latam_internal_type == "withhold"
            and self.l10n_ec_withholding_type in self.get_withhold_types()
        )

    def is_purchase_withhold(self):
        return self.l10n_ec_withholding_type == "purchase" and self.is_withhold()

    def is_sale_withhold(self):
        return self.l10n_ec_withholding_type == "sale" and self.is_withhold()

    def action_try_create_ecuadorian_withhold(self):
        action = {}
        if any(
            move.is_purchase_document() and move.l10n_ec_withhold_active
            for move in self
        ):
            if len(self) > 1:
                raise UserError(
                    _(
                        "You can't create Withhold for some invoice, "
                        "Please select only a Invoice."
                    )
                )
            action = self._action_create_purchase_withhold_wizard()
        elif any(
            move.is_sale_document() and move.l10n_ec_withhold_active for move in self
        ):
            action = self._action_create_sale_withhold_wizard()
        else:
            raise UserError(
                _(
                    "Please select only invoice "
                    "what satisfies the requirements for create withhold"
                )
            )
        return action

    def _action_create_sale_withhold_wizard(self):
        action = self.env.ref(
            "l10n_ec_withhold.l10n_ec_wizard_sale_withhold_action_window"
        ).read()[0]
        action["views"] = [
            (
                self.env.ref(
                    "l10n_ec_withhold.l10n_ec_wizard_sale_withhold_form_view"
                ).id,
                "form",
            )
        ]
        ctx = safe_eval(action["context"])
        ctx.pop("default_type", False)
        ctx.update(self.env.context.copy())
        action["context"] = ctx
        return action

    def _action_create_purchase_withhold_wizard(self):
        self.ensure_one()
        action = self.env.ref(
            "l10n_ec_withhold.l10n_ec_wizard_purchase_withhold_action_window"
        ).read()[0]
        action["views"] = [
            (
                self.env.ref(
                    "l10n_ec_withhold.l10n_ec_wizard_purchase_withhold_form_view"
                ).id,
                "form",
            )
        ]
        ctx = safe_eval(action["context"])
        ctx.pop("default_type", False)
        ctx.update(
            {
                "default_partner_id": self.partner_id.id,
                "default_invoice_id": self.id,
                "default_issue_date": self.invoice_date,
            }
        )
        action["context"] = ctx
        return action

    def action_show_l10n_ec_withholds(self):
        withhold_ids = self.l10n_ec_withhold_ids.ids
        action = self.env.ref("account.action_move_journal_line").read()[0]
        context = {
            "create": False,
            "delete": True,
            "edit": False,
        }
        action["context"] = context
        action["name"] = _("Withholding")
        view_tree_id = self.env.ref(
            "l10n_ec_withhold.view_account_move_withhold_tree"
        ).id
        view_form_id = self.env.ref(
            "l10n_ec_withhold.view_account_move_withhold_form"
        ).id
        action["view_mode"] = "form"
        action["views"] = [(view_form_id, "form")]
        action["res_id"] = withhold_ids[0]
        if len(withhold_ids) > 1:
            action["view_mode"] = "tree,form"
            action["views"] = [(view_tree_id, "tree"), (view_form_id, "form")]
            action["domain"] = [("id", "in", withhold_ids)]

        return action

    def _l10n_ec_get_document_date(self):
        if self.is_purchase_withhold():
            return self.date
        return super()._l10n_ec_get_document_date()

    def _get_l10n_ec_identification_type(self):
        # inherit considering withholding
        # base module only return data for invoices
        self.ensure_one()
        if self.is_purchase_withhold():
            it_ruc = self.env.ref("l10n_ec.ec_ruc", False)
            it_dni = self.env.ref("l10n_ec.ec_dni", False)
            it_passport = self.env.ref("l10n_ec.ec_passport", False)
            partner_identification = (
                self.commercial_partner_id.l10n_latam_identification_type_id
            )
            # final consumer by default
            identification_code = "07"
            if partner_identification.id == it_ruc.id:
                identification_code = "04"
            elif partner_identification.id == it_dni.id:
                identification_code = "05"
            elif partner_identification.id == it_passport.id:
                identification_code = "06"
            return identification_code
        return super()._get_l10n_ec_identification_type()

    def _get_l10n_latam_documents_domain(self):
        # support to withholding
        if (
            self.company_id.account_fiscal_country_id.code == "EC"
            and self.is_withhold()
        ):
            return [
                ("country_id.code", "=", "EC"),
                ("internal_type", "=", "withhold"),
            ]
        return super()._get_l10n_latam_documents_domain()

    def _get_l10n_ec_tax_support(self):
        self.ensure_one()
        return self.partner_id.l10n_ec_tax_support


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    l10n_ec_withhold_id = fields.Many2one(
        comodel_name="account.move",
        string="Withhold",
        readonly=True,
        copy=False,
    )

    l10n_ec_tax_support = fields.Selection(
        TAX_SUPPORT,
        string="Tax Support",
        copy=False,
        help="Tax support in invoice line",
    )
    l10n_ec_invoice_withhold_id = fields.Many2one(
        comodel_name="account.move",
        string="Invoice",
        readonly=True,
        copy=False,
    )

    @api.onchange("name", "product_id")
    def _onchange_get_l10n_ec_tax_support(self):
        for line in self:
            line.l10n_ec_tax_support = line._get_l10n_ec_tax_support()

    def _get_l10n_ec_tax_support(self):
        self.ensure_one()
        if (
            not self.l10n_ec_tax_support
            and self.move_id
            and self.move_id.l10n_ec_tax_support
        ):
            return self.move_id.l10n_ec_tax_support
        return False
