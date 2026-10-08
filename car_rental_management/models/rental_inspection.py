# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import _, api, fields, models
from odoo.exceptions import UserError

FUEL_LEVELS = [
    ('empty', 'Empty'),
    ('quarter', '1/4'),
    ('half', '1/2'),
    ('three_quarter', '3/4'),
    ('full', 'Full'),
]

CLEANLINESS_LEVELS = [
    ('clean', 'Clean'),
    ('acceptable', 'Acceptable'),
    ('dirty', 'Dirty'),
]

CHECKLIST_AREAS = [
    ('exterior', 'Exterior'),
    ('interior', 'Interior'),
    ('equipment', 'Equipment'),
    ('documents', 'Documents'),
    ('tracker', 'Tracker'),
    ('other', 'Other'),
]

DEFAULT_CHECKLIST = [
    ('exterior', 'Bumpers'),
    ('exterior', 'Sides'),
    ('exterior', 'Bonnet'),
    ('exterior', 'Roof'),
    ('exterior', 'Lights'),
    ('exterior', 'Windscreen'),
    ('interior', 'Seats'),
    ('interior', 'Dashboard'),
    ('interior', 'Mats'),
    ('interior', 'Boot'),
    ('equipment', 'Spare wheel'),
    ('equipment', 'Jack'),
    ('equipment', 'Wheel spanner'),
    ('equipment', 'Warning triangle'),
    ('documents', 'Required documents present'),
    ('tracker', 'Tracker installed and operational'),
]


class CarRentalInspection(models.Model):
    _name = 'car.rental.inspection'
    _description = 'Rental Inspection'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'inspection_date desc'
    _rec_names_search = ['name']

    name = fields.Char(
        string='Reference', default=lambda self: _('New'), copy=False, required=True)
    inspection_type = fields.Selection(
        selection=[('pickup', 'Pickup / Handover'), ('return', 'Return')],
        string='Inspection Type', required=True)
    rental_order_id = fields.Many2one(
        'sale.order', string='Rental Order', required=True, ondelete='cascade',
        domain="[('rental_state', 'in', ('confirmed', 'active', 'returned'))]")
    vehicle_id = fields.Many2one(
        'fleet.vehicle', string='Vehicle', required=True, check_company=True,
        default=lambda self: self._default_vehicle_id())
    customer_id = fields.Many2one(related='rental_order_id.partner_id', string='Customer', store=True)
    inspector_id = fields.Many2one(
        'res.users', string='Inspector', default=lambda self: self.env.user)
    inspection_date = fields.Datetime(
        string='Inspection Date/Time', default=fields.Datetime.now, required=True)
    mileage = fields.Float(string='Odometer (km)')
    fuel_level = fields.Selection(selection=FUEL_LEVELS, string='Fuel Level')
    cleanliness = fields.Selection(selection=CLEANLINESS_LEVELS, string='Cleanliness')
    line_ids = fields.One2many('car.rental.inspection.line', 'inspection_id', string='Checklist')
    damage_detected = fields.Boolean(string='Damage Detected', compute='_compute_damage_detected', store=True)
    notes = fields.Text(string='Notes')
    attachment_ids = fields.Many2many('ir.attachment', string='Photos')
    state = fields.Selection(
        selection=[('draft', 'Draft'), ('done', 'Completed')],
        string='Status', default='draft', tracking=True)
    company_id = fields.Many2one(
        related='rental_order_id.company_id', store=True, readonly=True)

    @api.model
    def _default_vehicle_id(self):
        return self.env.context.get('default_vehicle_id', False)

    @api.depends('line_ids.result')
    def _compute_damage_detected(self):
        for inspection in self:
            inspection.damage_detected = any(line.result == 'damage' for line in inspection.line_ids)

    @api.onchange('inspection_type')
    def _onchange_inspection_type(self):
        if not self.line_ids:
            self.line_ids = [
                fields.Command.create({'item': item, 'area': area})
                for area, item in DEFAULT_CHECKLIST
            ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                seq = self.env['ir.sequence'].next_by_code('car.rental.inspection') or _('New')
                vals['name'] = seq
            if not vals.get('line_ids') and vals.get('inspection_type'):
                vals['line_ids'] = [
                    fields.Command.create({'item': item, 'area': area})
                    for area, item in DEFAULT_CHECKLIST
                ]
        return super().create(vals_list)

    def action_done(self):
        for inspection in self:
            if inspection.state == 'done':
                continue
            if inspection.mileage <= 0:
                raise UserError(_('Record the odometer reading to complete the inspection.'))
            inspection.state = 'done'
            order = inspection.rental_order_id
            if inspection.inspection_type == 'pickup':
                order.inspection_status = 'pickup_done'
                order.pickup_mileage = inspection.mileage
            else:
                order.inspection_status = 'return_done'
                order.return_mileage = inspection.mileage
                order.damage_detected = inspection.damage_detected
                if inspection.damage_detected:
                    order.damage_ids._sync_from_inspection(inspection)

    def action_reset(self):
        self.write({'state': 'draft'})


class CarRentalInspectionLine(models.Model):
    _name = 'car.rental.inspection.line'
    _description = 'Rental Inspection Item'
    _order = 'area asc, id asc'

    inspection_id = fields.Many2one('car.rental.inspection', string='Inspection', required=True, ondelete='cascade')
    area = fields.Selection(selection=CHECKLIST_AREAS, string='Area', required=True)
    item = fields.Char(string='Check', required=True)
    result = fields.Selection(
        selection=[('ok', 'OK'), ('damage', 'Damage'), ('na', 'N/A')],
        string='Result', default='ok', required=True)
    notes = fields.Char(string='Notes')
