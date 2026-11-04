"""Rental operational fields on standard Fleet vehicles."""
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.addons.fleet.models.fleet_vehicle_model import FUEL_TYPES

from .pricing import require_role
from .workflow import window


class FleetVehicle(models.Model):
    _inherit = 'fleet.vehicle'

    rental_status = fields.Selection([
        ('setup', 'Needs Setup'),
        ('available', 'Available'),
        ('reserved', 'Reserved'),
        ('rented', 'Rented'),
        ('returned', 'Returned'),
        ('inspection', 'Inspection'),
        ('cleaning', 'Cleaning'),
        ('maintenance', 'Maintenance'),
        ('damaged', 'Accident / Damaged'),
        ('decommissioned', 'Decommissioned'),
    ], string='Rental Availability', default='setup', required=True, tracking=True, copy=False)
    rental_category_id = fields.Many2one(
        related='category_id', string='Rental Category', store=True, tracking=True)
    rental_daily_rate = fields.Monetary(string='Legacy Daily Rate', currency_field='currency_id', default=0,
                                        help='Legacy vehicle rate. New reservations use approved destination pricing rules.')
    rental_tracker_working = fields.Boolean(string='Tracker Operational', default=True)
    rental_service_interval = fields.Float(string='Service Interval (km)', default=10000)
    rental_next_service_mileage = fields.Float()
    rental_next_service_date = fields.Date()
    rental_service_due = fields.Boolean(compute='_compute_rental_service_due')
    rental_document_ids = fields.Many2many('ir.attachment', 'fleet_vehicle_rental_document_rel', string='Vehicle Documents')
    rental_image = fields.Image(string='Vehicle Photo')
    rental_revenue = fields.Monetary(compute='_compute_rental_financials', string='Rental Revenue')
    rental_maintenance_cost = fields.Monetary(compute='_compute_rental_financials', string='Maintenance Cost')
    rental_reservations_count = fields.Integer(compute='_compute_rental_counts')
    rental_rentals_count = fields.Integer(compute='_compute_rental_counts')
    rental_vehicle_count = fields.Integer(compute='_compute_rental_counts')
    equipment_id = fields.Many2one('maintenance.equipment', check_company=True, copy=False)
    maintenance_request_ids = fields.One2many('maintenance.request', 'rental_vehicle_id', string='Rental Maintenance Requests')

    @api.depends('odometer', 'rental_next_service_mileage', 'rental_next_service_date')
    def _compute_rental_service_due(self):
        today = fields.Date.today()
        for vehicle in self:
            vehicle.rental_service_due = bool(
                (vehicle.rental_next_service_mileage and vehicle.odometer >= vehicle.rental_next_service_mileage - 500)
                or (vehicle.rental_next_service_date and vehicle.rental_next_service_date <= today + timedelta(days=7))
            )

    @api.depends('rental_vehicle_count')
    def _compute_rental_counts(self):
        Rentals = self.env['car.rental.rental']
        for vehicle in self:
            reservations = self.env['car.rental.reservation'].search_count([('vehicle_id', '=', vehicle.id)])
            rentals = Rentals.search_count([('vehicle_id', '=', vehicle.id)])
            vehicle.rental_reservations_count = reservations
            vehicle.rental_rentals_count = rentals
            vehicle.rental_vehicle_count = 0

    @api.depends('rental_rentals_count', 'currency_id')
    def _compute_rental_financials(self):
        invoices = self.env['account.move']
        requests = self.env['maintenance.request']
        for vehicle in self:
            rental_moves = self.env['car.rental.rental'].search([('vehicle_id', '=', vehicle.id)]).mapped('invoice_ids').filtered(
                lambda m: m.state == 'posted' and m.rental_invoice_kind == 'rental')
            vehicle.rental_revenue = sum(rental_moves.mapped('amount_untaxed_signed'))
            vehicle.rental_maintenance_cost = sum(requests.search([('rental_vehicle_id', '=', vehicle.id)]).mapped('rental_cost'))

    @api.constrains('license_plate', 'rental_service_interval', 'odometer')
    def _validate_rental_vehicle(self):
        for record in self:
            if record.rental_service_interval <= 0 or record.odometer < 0:
                raise ValidationError(_('Mileage cannot be negative and service intervals must be positive.'))

    def _check_ready(self, handover=False):
        for vehicle in self:
            if not vehicle.license_plate or not vehicle.rental_category_id:
                raise ValidationError(_('Complete the vehicle registration and rental category before allocation.'))
            allowed = ('available', 'reserved') if handover else ('available', 'reserved', 'rented')
            if vehicle.rental_status not in allowed:
                raise ValidationError(_('The vehicle is not available for rental.'))
            if vehicle.company_id.rental_block_expired_documents:
                today = fields.Date.today()
                contract = vehicle._rental_open_contract('Road Licence')
                if not contract or not contract.expiration_date or contract.expiration_date < today:
                    raise ValidationError(_('This vehicle needs a current Road Licence contract in Fleet before pickup. This is separate from the customer driving licence. Insurance is optional.'))
            if vehicle.company_id.rental_block_tracker and not vehicle.rental_tracker_working:
                raise ValidationError(_('The vehicle tracker must be operational.'))

    def _rental_open_contract(self, kind):
        self.ensure_one()
        subtype = self.env['fleet.service.type'].search([('category', '=', 'contract'), ('name', '=', kind)], limit=1)
        if not subtype:
            return self.env['fleet.vehicle.log.contract']
        return self.env['fleet.vehicle.log.contract'].search([
            ('vehicle_id', '=', self.id),
            ('cost_subtype_id', '=', subtype.id),
            ('state', 'in', ('open', 'expired', 'tocover')),
        ], order='expiration_date desc', limit=1)

    def _refresh_reserved_status(self):
        for vehicle in self:
            if vehicle.rental_status in ('available', 'reserved'):
                reserved = self.env['car.rental.reservation'].search_count([
                    ('vehicle_id', '=', vehicle.id), ('status', '=', 'confirmed'),
                    ('expected_return_datetime', '>=', fields.Datetime.now()), ('rental_ids', '=', False)])
                vehicle.sudo()._operational_update({'rental_status': 'reserved' if reserved else 'available'})

    def write(self, vals):
        if set(vals) - {'message_follower_ids', 'rental_status', 'odometer'}:
            require_role(self.env, 'group_fleet_manager')
        if 'rental_status' in vals:
            for vehicle in self:
                if vals['rental_status'] in ('rented', 'reserved', 'returned', 'inspection'):
                    raise ValidationError(_('Use the booking, pickup or return workflow for operational states.'))
                if vehicle.rental_ids.filtered(lambda r: r.status == 'ongoing'):
                    raise ValidationError(_('Return the ongoing rental before changing the vehicle state.'))
                if vals['rental_status'] == 'available':
                    if not vehicle.license_plate or not vehicle.rental_category_id:
                        raise ValidationError(_('Complete the registration number and rental category before making the vehicle available.'))
                    if vehicle.rental_status not in ('setup', 'available', 'reserved', 'cleaning'):
                        raise ValidationError(_('Complete inspection, repairs and cleaning before releasing the vehicle.'))
                    if vehicle.rental_ids.mapped('damage_ids').filtered(lambda d: d.state != 'closed'):
                        raise ValidationError(_('Resolve outstanding damage cases before releasing the vehicle.'))
        return super().write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('rental_next_service_mileage'):
                interval = vals.get('rental_service_interval', 10000)
                if interval > 0:
                    vals['rental_next_service_mileage'] = vals.get('odometer', 0) + interval
        return super().create(vals_list)

    def _operational_update(self, vals):
        if set(vals) - {'rental_status', 'odometer'}:
            raise ValidationError(_('Only odometer and operational status can be updated by a handover.'))
        return super(FleetVehicle, self.sudo()).write(vals)

    def action_rental_reservations(self):
        self.ensure_one()
        return window(_('Vehicle Reservations'), 'car.rental.reservation',
                      [('vehicle_id', '=', self.id)], {'default_vehicle_id': self.id})

    def action_rental_rentals(self):
        self.ensure_one()
        return window(_('Vehicle Rentals'), 'car.rental.rental', [('vehicle_id', '=', self.id)])

    def action_rental_book(self):
        self.ensure_one()
        self._check_ready()
        if self.rental_status == 'maintenance':
            raise ValidationError(_('A vehicle in maintenance cannot be reserved.'))
        return dict(window(_('New Reservation'), 'car.rental.journey',
                           context={'default_vehicle_id': self.id, 'default_company_id': self.company_id.id}), view_mode='form')

    def action_activate(self):
        require_role(self.env, 'group_fleet_manager')
        for record in self:
            if record.rental_status != 'setup' or not record.license_plate or not record.rental_category_id:
                raise ValidationError(_('Enter the registration number and rental category before activating a setup vehicle.'))
            record.rental_status = 'available'

    def action_mark_cleaning(self):
        require_role(self.env, 'group_fleet_manager')
        for vehicle in self:
            if vehicle.rental_status not in ('inspection', 'returned'):
                raise ValidationError(_('Only returned, inspected vehicles can enter cleaning.'))
            if vehicle.rental_ids.filtered(lambda r: r.status == 'returned' and not r.return_inspection_done):
                raise ValidationError(_('Complete the return inspection first.'))
            if vehicle.rental_ids.mapped('damage_ids').filtered(lambda d: d.state != 'closed'):
                raise ValidationError(_('Resolve all damage assessments and repairs first.'))
            vehicle.rental_status = 'cleaning'

    def action_release(self):
        require_role(self.env, 'group_fleet_manager')
        for vehicle in self:
            if vehicle.rental_status != 'cleaning':
                raise ValidationError(_('Complete cleaning before releasing the vehicle.'))
            vehicle.rental_status = 'available'
            vehicle._refresh_reserved_status()

    def action_rental_maintenance(self):
        require_role(self.env, 'group_fleet_manager')
        self.ensure_one()
        if not self.equipment_id:
            self.equipment_id = self.env['maintenance.equipment'].create({'name': self.display_name, 'company_id': self.company_id.id})
        return window(_('Vehicle Maintenance'), 'maintenance.request',
                      [('rental_vehicle_id', '=', self.id)],
                      {'default_rental_vehicle_id': self.id, 'default_equipment_id': self.equipment_id.id, 'default_company_id': self.company_id.id})

    def get_formview_action(self, access_uid=None):
        self.ensure_one()
        return super().get_formview_action(access_uid=access_uid)

    @api.model
    def _cron_rental_reminders(self):
        activity = self.env.ref('mail.mail_activity_data_todo')
        for company in self.env['res.company'].search([]):
            vehicles = self.with_company(company).search([('company_id', '=', company.id), ('rental_status', '!=', 'decommissioned')])
            for vehicle in vehicles:
                vehicle._refresh_reserved_status()
                for kind, label in (('Insurance', 'Insurance expiry'), ('Road Licence', 'Road licence expiry')):
                    contract = vehicle._rental_open_contract(kind)
                    if contract and contract.expiration_date and contract.expiration_date <= fields.Date.today() + timedelta(days=30):
                        vehicle._schedule_once(activity, label, vehicle.manager_id, contract.expiration_date)
                if vehicle.rental_service_due:
                    vehicle._schedule_once(activity, 'Vehicle service due', vehicle.manager_id, fields.Date.today())
                    if not vehicle.maintenance_request_ids.filtered(lambda r: not r.stage_id.done and not r.archive):
                        if not vehicle.equipment_id:
                            vehicle.equipment_id = self.env['maintenance.equipment'].create({'name': vehicle.display_name, 'company_id': company.id})
                        self.env['maintenance.request'].create({
                            'name': 'Scheduled service: ' + vehicle.display_name,
                            'rental_vehicle_id': vehicle.id, 'equipment_id': vehicle.equipment_id.id,
                            'company_id': company.id, 'maintenance_type': 'preventive'})
            rentals = self.env['car.rental.rental'].search([('company_id', '=', company.id)])
            for rental in rentals:
                if rental.status == 'ongoing' and rental.expected_return_datetime and rental.expected_return_datetime < fields.Datetime.now():
                    rental._schedule_once(activity, 'Overdue vehicle return', rental.responsible_id, fields.Date.today())
                if rental.balance_due > 0 and rental.start_date <= fields.Date.today():
                    rental._schedule_once(activity, 'Outstanding rental payment', rental.responsible_id, fields.Date.today())
                if rental.status == 'returned' and not rental.return_inspection_done:
                    rental._schedule_once(activity, 'Pending return inspection', rental.responsible_id, fields.Date.today())
            for damage in self.env['car.rental.damage.case'].search([('company_id', '=', company.id), ('state', '=', 'draft')]):
                damage._schedule_once(activity, 'Pending damage assessment', damage.rental_id.responsible_id, fields.Date.today())

    def _schedule_once(self, activity, summary, user, deadline):
        if not self.activity_ids.filtered(lambda a: a.activity_type_id == activity and a.summary == summary):
            self.activity_schedule('mail.mail_activity_data_todo', summary=summary, user_id=(user or self.env.user).id, date_deadline=deadline)
