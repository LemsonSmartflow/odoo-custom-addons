"""Rental operational fields on standard Fleet vehicles."""
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

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
        related='category_id', string='Rental Category', store=True, tracking=True,
        readonly=False)
    rental_daily_rate = fields.Monetary(string='Legacy Daily Rate', currency_field='currency_id', default=0,
                                        help='Legacy vehicle rate. New reservations use approved destination pricing rules.')
    rental_tracker_working = fields.Boolean(string='Tracker Operational', default=True)
    rental_service_interval = fields.Float(string='Service Interval (km)', default=10000)
    rental_next_service_mileage = fields.Float()
    rental_next_service_date = fields.Date()
    rental_service_due = fields.Boolean(compute='_compute_rental_service_due')
    rental_document_ids = fields.Many2many('ir.attachment', 'fleet_vehicle_rental_document_rel', string='Vehicle Documents')
    # Single source of truth: the native Fleet image.  ``rental_image`` is kept
    # as a writable alias so existing views/tests keep working without showing
    # a different picture in each app.
    rental_image = fields.Image(related='image_1920', string='Vehicle Photo', readonly=False)
    rental_revenue = fields.Monetary(compute='_compute_rental_financials', string='Rental Revenue')
    rental_maintenance_cost = fields.Monetary(compute='_compute_rental_financials', string='Maintenance Cost')
    rental_reservations_count = fields.Integer(compute='_compute_rental_counts')
    rental_rentals_count = fields.Integer(compute='_compute_rental_counts')
    rental_vehicle_count = fields.Integer(compute='_compute_rental_counts')
    equipment_id = fields.Many2one('maintenance.equipment', check_company=True, copy=False)
    maintenance_request_ids = fields.One2many('maintenance.request', 'rental_vehicle_id', string='Rental Maintenance Requests')

    def _vehicle_maintenance_domain(self):
        self.ensure_one()
        domain = [('rental_vehicle_id', '=', self.id)]
        if self.equipment_id:
            domain = ['|', ('rental_vehicle_id', '=', self.id),
                      ('equipment_id', '=', self.equipment_id.id)]
        return domain

    def _all_maintenance_requests(self):
        self.ensure_one()
        return self.env['maintenance.request'].with_context(active_test=False).search(
            self._vehicle_maintenance_domain())

    def _open_maintenance_requests(self):
        self.ensure_one()
        return self.env['maintenance.request'].search(
            self._vehicle_maintenance_domain() + [('stage_id.done', '=', False)])

    def _ensure_equipment(self):
        self.ensure_one()
        if not self.equipment_id:
            self.sudo().write({
                'equipment_id': self.env['maintenance.equipment'].sudo().create({
                    'name': self.display_name,
                    'company_id': self.company_id.id,
                    'technician_user_id': (self.manager_id or self.env.user).id,
                }).id,
            })
        return self.equipment_id

    @api.depends('odometer', 'rental_next_service_mileage', 'rental_next_service_date')
    def _compute_rental_service_due(self):
        for vehicle in self:
            today = fields.Date.context_today(vehicle)
            vehicle.rental_service_due = bool(
                (vehicle.rental_next_service_mileage and vehicle.odometer >= vehicle.rental_next_service_mileage - 500)
                or (vehicle.rental_next_service_date and vehicle.rental_next_service_date <= today + timedelta(days=7))
            )

    @api.depends('reservation_ids', 'rental_ids')
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
            vehicle.rental_maintenance_cost = sum(
                request.rental_cost for request in vehicle._all_maintenance_requests()
                if not request.archive)

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
                today = fields.Date.context_today(vehicle)
                contract = vehicle._rental_open_contract('Road Licence')
                if (
                    not contract or not contract.expiration_date
                    or contract.expiration_date < today
                    or (contract.start_date and contract.start_date > today)
                ):
                    raise ValidationError(_('This vehicle needs a current Road Licence contract in Fleet before pickup. This is separate from the customer driving licence. Insurance is optional.'))
            if vehicle.company_id.rental_block_tracker and not vehicle.rental_tracker_working:
                raise ValidationError(_('The vehicle tracker must be operational.'))

    def _rental_open_contract(self, kind):
        self.ensure_one()
        subtype = self.env['fleet.service.type'].search([('category', '=', 'contract'), ('name', '=', kind)], limit=1)
        if not subtype:
            return self.env['fleet.vehicle.log.contract']
        contracts = self.env['fleet.vehicle.log.contract'].search([
            ('vehicle_id', '=', self.id),
            ('cost_subtype_id', '=', subtype.id),
            ('state', 'in', ('open', 'futur', 'expired')),
        ], order='expiration_date desc')
        priority = {'open': 0, 'futur': 1, 'expired': 2}
        return contracts.sorted(key=lambda contract: (
            priority.get(contract.state, 3),
            -contract.expiration_date.toordinal() if contract.expiration_date else 0,
        ))[:1]

    def _refresh_reserved_status(self):
        for vehicle in self:
            if vehicle.rental_status in ('available', 'reserved'):
                # A confirmed reservation still holds the car even after its
                # draft rental has been created; dropping the old rental_ids
                # filter prevents the daily cron from flipping it to available
                # in the middle of a live booking.
                reserved = self.env['car.rental.reservation'].search_count([
                    ('vehicle_id', '=', vehicle.id), ('status', '=', 'confirmed'),
                    ('expected_return_datetime', '>=', fields.Datetime.now())])
                vehicle.sudo()._operational_update({'rental_status': 'reserved' if reserved else 'available'})

    def write(self, vals):
        # Only rental-specific fields require the rental Fleet Manager role.
        # Core Fleet fields (state_id, driver, model, active, odometer, ...) stay
        # governed by native Fleet ACLs so standard Fleet users and Odoo's own
        # flows (e.g. applying a new driver) keep working.
        operational = {'rental_status', 'odometer'}
        rental_fields = {
            name for name in vals
            if name in self._fields and name not in operational
            and (name.startswith('rental_') or name in ('equipment_id',))
        }
        if rental_fields:
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
                    # A vehicle must have completed its return inspection before it
                    # can be released for another hire, and no service request may
                    # still be open.
                    if vehicle.rental_ids.filtered(
                            lambda r: r.status == 'returned' and not r.return_inspection_done):
                        raise ValidationError(_('Complete the return inspection before releasing the vehicle.'))
                    if vehicle._open_maintenance_requests():
                        raise ValidationError(_('Complete all open maintenance requests before releasing the vehicle.'))
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

    def _set_rental_odometer(self, value, reading_date):
        """Record a rental odometer reading with the actual inspection date.

        Writing ``fleet.vehicle.odometer`` through the ORM dates the native log
        as "today", which breaks mileage-over-time reporting for pickups and
        returns inspected on a different day.
        """
        self.ensure_one()
        if value <= 0 or value < self.odometer:
            return False
        self.env['fleet.vehicle.odometer'].sudo().create({
            'vehicle_id': self.id,
            'value': value,
            'date': reading_date or fields.Date.context_today(self),
        })
        self.invalidate_recordset(['odometer'])
        return True

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
    def _cron_rental_handover_reminders(self):
        now = fields.Datetime.now()
        rentals = self.env['car.rental.rental'].search([
            ('status', '=', 'draft'),
            ('reservation_id.status', '=', 'confirmed'),
            ('reservation_id.pickup_datetime', '>', now),
            ('reservation_id.pickup_datetime', '<=', now + timedelta(hours=4)),
            ('handover_reminder_sent', '=', False),
        ])
        rentals._schedule_handover_reminder()

    @api.model
    def _repair_stuck_rental_states(self):
        """Self-heal legacy hold/step mismatches without waiting for an upgrade."""
        for vehicle in self.sudo().search([('rental_status', 'in', ('available', 'reserved'))]):
            try:
                vehicle._refresh_reserved_status()
            except Exception:
                continue
        for reservation in self.env['car.rental.reservation'].sudo().search([
                ('status', '=', 'confirmed')]):
            rentals = reservation.rental_ids
            if rentals and all(r.status == 'cancelled' for r in rentals):
                try:
                    reservation.with_context(skip_rental_cancel=True).action_cancel()
                except Exception:
                    continue
            journey = self.env['car.rental.journey'].sudo().search(
                [('reservation_id', '=', reservation.id)], limit=1)
            if journey:
                try:
                    journey._reconcile_step()
                except Exception:
                    continue
        return True

    @api.model
    def _cron_rental_reminders(self):
        self._repair_stuck_rental_states()
        activity = self.env.ref('mail.mail_activity_data_todo')
        for company in self.env['res.company'].search([]):
            vehicles = self.with_company(company).search([('company_id', '=', company.id), ('rental_status', '!=', 'decommissioned')])
            for vehicle in vehicles:
                vehicle._refresh_reserved_status()
                for kind, label in (('Insurance', 'Insurance expiry'), ('Road Licence', 'Road licence expiry')):
                    contract = vehicle._rental_open_contract(kind)
                    today_local = fields.Date.context_today(vehicle)
                    if contract and contract.expiration_date and contract.expiration_date <= today_local + timedelta(days=30):
                        vehicle._schedule_once(activity, label, vehicle.manager_id, contract.expiration_date)
                if vehicle.rental_service_due:
                    today_local = fields.Date.context_today(vehicle)
                    vehicle._schedule_once(activity, 'Vehicle service due', vehicle.manager_id, today_local)
                    # A request may have been completed natively without updating
                    # the vehicle's next-service targets.  Look for any recent
                    # service request before creating another one.
                    requests = vehicle._all_maintenance_requests()
                    recent = requests.filtered(
                        lambda r: r.stage_id.done and r.request_date
                        and r.request_date >= (vehicle.rental_next_service_date or today_local))
                    if not requests.filtered(lambda r: not r.stage_id.done and not r.archive) and not recent:
                        equipment = vehicle._ensure_equipment()
                        self.env['maintenance.request'].create({
                            'name': 'Scheduled service: ' + vehicle.display_name,
                            'rental_vehicle_id': vehicle.id, 'equipment_id': equipment.id,
                            'company_id': company.id, 'maintenance_type': 'preventive',
                            'user_id': vehicle.manager_id.id,
                        })
            rentals = self.env['car.rental.rental'].search([('company_id', '=', company.id)])
            for rental in rentals:
                today = fields.Date.context_today(rental)
                if rental.status == 'ongoing' and rental.expected_return_datetime:
                    return_day = fields.Datetime.context_timestamp(
                        rental, rental.expected_return_datetime).date()
                    if return_day == today + timedelta(days=1):
                        rental._schedule_once(
                            activity, 'Vehicle return due tomorrow',
                            rental.responsible_id, today)
                    if rental.expected_return_datetime < fields.Datetime.now():
                        rental._schedule_once(
                            activity, 'Overdue vehicle return',
                            rental.responsible_id, today)
                if rental.balance_due > 0 and rental.start_date <= today:
                    rental._schedule_once(activity, 'Outstanding rental payment', rental.responsible_id, today)
                if rental.status == 'returned' and not rental.return_inspection_done:
                    rental._schedule_once(activity, 'Pending return inspection', rental.responsible_id, today)
            for damage in self.env['car.rental.damage.case'].search([('company_id', '=', company.id), ('state', '=', 'draft')]):
                damage._schedule_once(
                    activity, 'Pending damage assessment',
                    damage.rental_id.responsible_id, fields.Date.context_today(damage))
        # Expired rental quotations are handled by the sale.order cron registered
        # in data/reminders.xml, not by the fleet reminder job.

    def _schedule_once(self, activity, summary, user, deadline):
        if not self.activity_ids.filtered(lambda a: a.activity_type_id == activity and a.summary == summary):
            self.activity_schedule('mail.mail_activity_data_todo', summary=summary, user_id=(user or self.env.user).id, date_deadline=deadline)
