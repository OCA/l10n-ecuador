from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command

from .utils import records_action

TRANSPORT_TYPES = [("water", "Sea"), ("air", "Air"), ("land", "Land")]

EVENT_TYPES = [
    ("booked", "Booked"),
    ("departed", "Departed"),
    ("transshipment", "Transshipment"),
    ("arrived", "Arrived"),
    ("customs", "In Customs"),
    ("released", "Released (Levante)"),
    ("delivered", "Delivered to Warehouse"),
    ("other", "Other"),
]

DOCUMENT_TYPES = [
    ("bl", "Bill of Lading (BL)"),
    ("awb", "Air Waybill (AWB)"),
    ("waybill", "Road Waybill (CPIC)"),
    ("commercial_invoice", "Commercial Invoice"),
    ("packing_list", "Packing List"),
    ("insurance_policy", "Insurance Policy"),
    ("origin_certificate", "Certificate of Origin"),
    ("control_document", "Prior Control Document"),
    ("dai", "Customs Declaration (DAI)"),
    ("other", "Other"),
]


class L10nEcImportShipment(models.Model):
    _name = "l10n_ec.import.shipment"
    _description = "Import Shipment"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"
    _check_company_auto = True

    name = fields.Char(default=lambda self: self.env._("New"), copy=False, readonly=True, tracking=True)
    state = fields.Selection(
        [("draft", "Draft"), ("in_transit", "In Transit"), ("arrived", "Arrived"), ("done", "Done"), ("cancel", "Cancelled")],
        default="draft", required=True, readonly=True, copy=False, tracking=True,
    )
    company_id = fields.Many2one("res.company", required=True, index=True, default=lambda self: self.env.company)

    partner_id = fields.Many2one(
        "res.partner", string="Supplier / Shipper", required=True, tracking=True, check_company=True,
    )
    forwarder_id = fields.Many2one("res.partner", string="Freight Forwarder", tracking=True, check_company=True)
    carrier_id = fields.Many2one(
        "res.partner", string="Carrier", check_company=True, help="Shipping line, airline or trucking company.",
    )
    customs_agent_id = fields.Many2one("res.partner", string="Customs Broker", tracking=True, check_company=True)
    incoterm_id = fields.Many2one("account.incoterms", string="Incoterm")

    transport_type = fields.Selection(TRANSPORT_TYPES, string="Transport", required=True, default="water", tracking=True)
    water_type = fields.Selection([("fcl", "FCL"), ("lcl", "LCL")], string="Sea Load")
    land_type = fields.Selection([("ftl", "FTL"), ("ltl", "LTL")], string="Land Load")
    loading_port_id = fields.Many2one("l10n_ec.import.port", string="Port of Loading", check_company=True)
    discharging_port_id = fields.Many2one("l10n_ec.import.port", string="Port of Discharge", check_company=True)
    transport_document = fields.Char(
        string="BL / AWB / Waybill No.", tracking=True, copy=False,
        help="Master transport document number.",
    )
    voyage = fields.Char(string="Vessel / Flight / Voyage")

    etd = fields.Date(string="ETD", tracking=True, help="Estimated time of departure.")
    eta = fields.Date(string="ETA", tracking=True, help="Estimated time of arrival.")
    departure_date = fields.Date(copy=False, tracking=True)
    arrival_date = fields.Date(copy=False, tracking=True)

    purchase_order_ids = fields.Many2many(
        "purchase.order", string="Purchase Orders", check_company=True,
        domain="[('state', '=', 'purchase')]",
    )
    picking_ids = fields.Many2many("stock.picking", string="Receipts", compute="_compute_picking_ids")
    picking_count = fields.Integer(compute="_compute_picking_ids")
    container_ids = fields.One2many("l10n_ec.import.shipment.container", "shipment_id", string="Containers", copy=True)
    event_ids = fields.One2many("l10n_ec.import.shipment.event", "shipment_id", string="Tracking", copy=False)
    document_ids = fields.One2many("l10n_ec.import.document", "shipment_id", string="Documents", copy=False)
    import_ids = fields.One2many("l10n_ec.import", "shipment_id", string="Customs Declarations", copy=False)
    import_count = fields.Integer(compute="_compute_import_count")

    container_count = fields.Integer(compute="_compute_totals")
    total_weight = fields.Float(string="Gross Weight (kg)", compute="_compute_totals", digits="Stock Weight")
    total_volume = fields.Float(string="Volume (m³)", compute="_compute_totals", digits="Volume")
    total_packages = fields.Integer(string="Packages", compute="_compute_totals")
    note = fields.Html()

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    @api.depends("purchase_order_ids.picking_ids.state")
    def _compute_picking_ids(self):
        for shipment in self:
            pickings = shipment.purchase_order_ids.picking_ids.filtered(
                lambda p: p.picking_type_code == "incoming" and p.state != "cancel"
            )
            shipment.picking_ids = pickings
            shipment.picking_count = len(pickings)

    @api.depends("import_ids")
    def _compute_import_count(self):
        for shipment in self:
            shipment.import_count = len(shipment.import_ids)

    @api.depends("container_ids.gross_weight", "container_ids.volume", "container_ids.packages")
    def _compute_totals(self):
        for shipment in self:
            shipment.container_count = len(shipment.container_ids)
            shipment.total_weight = sum(shipment.container_ids.mapped("gross_weight"))
            shipment.total_volume = sum(shipment.container_ids.mapped("volume"))
            shipment.total_packages = sum(shipment.container_ids.mapped("packages"))

    @api.onchange("purchase_order_ids")
    def _onchange_purchase_order_ids(self):
        if not self.partner_id and self.purchase_order_ids:
            self.partner_id = self.purchase_order_ids[0].partner_id
        if not self.incoterm_id and self.purchase_order_ids:
            self.incoterm_id = self.purchase_order_ids[0].incoterm_id

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", self.env._("New")) == self.env._("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("l10n_ec.import.shipment") or self.env._("New")
        return super().create(vals_list)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_linked(self):
        if self.import_ids:
            raise UserError(self.env._("Delete or unlink its customs declarations before deleting a shipment."))

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------
    def _add_event(self, event_type, date=None, port=False):
        self.env["l10n_ec.import.shipment.event"].create([{
            "shipment_id": shipment.id,
            "event_type": event_type,
            "date": date or fields.Datetime.now(),
            "port_id": port.id if port else False,
        } for shipment in self])

    def action_depart(self):
        for shipment in self:
            if shipment.state != "draft":
                raise UserError(self.env._("Only draft shipments can depart."))
            shipment.write({
                "state": "in_transit",
                "departure_date": shipment.departure_date or fields.Date.context_today(self),
            })
            shipment._add_event("departed", port=shipment.loading_port_id)
        return True

    def action_arrive(self):
        for shipment in self:
            if shipment.state not in ("draft", "in_transit"):
                raise UserError(self.env._("The shipment %s has already arrived.", shipment.name))
            shipment.write({
                "state": "arrived",
                "arrival_date": shipment.arrival_date or fields.Date.context_today(self),
            })
            shipment._add_event("arrived", port=shipment.discharging_port_id)
        return True

    def action_done(self):
        for shipment in self:
            if shipment.state != "arrived":
                raise UserError(self.env._("The shipment must arrive before closing it."))
            if shipment.import_ids.filtered(lambda imp: imp.state not in ("published", "cancel")):
                raise UserError(self.env._("Publish or cancel the customs declarations of %s first.", shipment.name))
        self.state = "done"
        return True

    def action_cancel(self):
        if self.import_ids.filtered(lambda imp: imp.state == "published"):
            raise UserError(self.env._("A shipment with a published customs declaration cannot be cancelled."))
        self.state = "cancel"
        return True

    def action_reset_draft(self):
        self.filtered(lambda s: s.state == "cancel").state = "draft"
        return True

    def action_create_import(self):
        """Create the customs declaration (liquidation) from the done receipts."""
        self.ensure_one()
        receipts = self.picking_ids.filtered(lambda p: p.state == "done")
        if not receipts:
            raise UserError(self.env._("Validate at least one receipt of the purchase orders of this shipment first."))
        already = self.import_ids.filtered(lambda imp: imp.state != "cancel").picking_ids
        receipts -= already
        if not receipts:
            raise UserError(self.env._("Every done receipt is already in a customs declaration."))
        declaration = self.env["l10n_ec.import"].create({
            "shipment_id": self.id,
            "company_id": self.company_id.id,
            "picking_ids": [Command.set(receipts.ids)],
            "arrival_date": self.arrival_date,
            "customs_agent_id": self.customs_agent_id.id,
        })
        declaration.action_load_receipts()
        return records_action(declaration, self.env._("Customs Declaration"))

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------
    def action_view_imports(self):
        self.ensure_one()
        return records_action(self.import_ids, self.env._("Customs Declarations"))

    def action_view_pickings(self):
        self.ensure_one()
        return records_action(self.picking_ids, self.env._("Receipts"))


class L10nEcImportShipmentContainer(models.Model):
    _name = "l10n_ec.import.shipment.container"
    _description = "Shipment Container"
    _order = "shipment_id, sequence, id"

    shipment_id = fields.Many2one("l10n_ec.import.shipment", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="shipment_id.company_id", store=True, index=True)
    sequence = fields.Integer(default=10)
    container_type_id = fields.Many2one("l10n_ec.import.container.type", string="Type")
    name = fields.Char(string="Container No.", help="e.g. MSCU1234567")
    seal_number = fields.Char(string="Seal No.")
    packages = fields.Integer()
    gross_weight = fields.Float(string="Gross Weight (kg)", digits="Stock Weight")
    volume = fields.Float(string="Volume (m³)", digits="Volume")

    @api.constrains("gross_weight", "volume", "container_type_id")
    def _check_capacity(self):
        for container in self:
            ctype = container.container_type_id
            if ctype.max_weight and container.gross_weight > ctype.max_weight:
                raise ValidationError(self.env._(
                    "Container %(name)s exceeds the payload of a %(type)s (%(max)s kg).",
                    name=container.name or "", type=ctype.name, max=ctype.max_weight,
                ))
            if ctype.volume and container.volume > ctype.volume:
                raise ValidationError(self.env._(
                    "Container %(name)s exceeds the capacity of a %(type)s (%(max)s m³).",
                    name=container.name or "", type=ctype.name, max=ctype.volume,
                ))


class L10nEcImportShipmentEvent(models.Model):
    _name = "l10n_ec.import.shipment.event"
    _description = "Shipment Tracking Event"
    _order = "shipment_id, date desc, id desc"

    shipment_id = fields.Many2one("l10n_ec.import.shipment", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="shipment_id.company_id", store=True, index=True)
    date = fields.Datetime(required=True, default=fields.Datetime.now)
    event_type = fields.Selection(EVENT_TYPES, string="Event", required=True, default="other")
    port_id = fields.Many2one("l10n_ec.import.port", string="Location")
    note = fields.Char()

    @api.model_create_multi
    def create(self, vals_list):
        events = super().create(vals_list)
        labels = dict(EVENT_TYPES)
        for event in events:
            body = labels[event.event_type]
            if event.port_id:
                body += f" - {event.port_id.display_name}"
            if event.note:
                body += f": {event.note}"
            event.shipment_id.message_post(body=self.env._("Tracking: %s", body))
        return events


class L10nEcImportDocument(models.Model):
    _name = "l10n_ec.import.document"
    _description = "Import Supporting Document"
    _order = "shipment_id, document_type, id"

    shipment_id = fields.Many2one("l10n_ec.import.shipment", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="shipment_id.company_id", store=True, index=True)
    document_type = fields.Selection(DOCUMENT_TYPES, string="Type", required=True, default="other")
    name = fields.Char(string="Number")
    date = fields.Date()
    file = fields.Binary(attachment=True)
    file_name = fields.Char()
    note = fields.Char()
