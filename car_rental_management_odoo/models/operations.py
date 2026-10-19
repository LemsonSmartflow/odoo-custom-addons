from math import ceil
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from .pricing import require_role
from .workflow import window


class Rental(models.Model):
    _name = 'car.rental.rental'
    _inherit = ['car.rental.rental', 'mail.thread', 'mail.activity.mixin']

    company_id = fields.Many2one(related='reservation_id.company_id', store=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    responsible_id = fields.Many2one('res.users', default=lambda self: self.env.user)
    destination_id = fields.Many2one(related='reservation_id.destination_id', store=True)
    expected_return_datetime = fields.Datetime(related='reservation_id.expected_return_datetime')
    actual_pickup_datetime = fields.Datetime(readonly=True, copy=False)
    actual_return_datetime = fields.Datetime(readonly=True, copy=False)
    inspection_ids = fields.One2many('car.rental.check', 'rental_id')
    pickup_inspection_done = fields.Boolean(compute='_compute_inspections')
    return_inspection_done = fields.Boolean(compute='_compute_inspections')
    damage_ids = fields.One2many('car.rental.damage.case', 'rental_id')
    agreement_terms = fields.Text()
    agreement_signature = fields.Image(string='Customer Signature', copy=False)
    agreement_signed_by = fields.Char(copy=False)
    agreement_signed_on = fields.Datetime(readonly=True, copy=False)
    agreement_state = fields.Selection([('draft', 'Awaiting Signature'), ('signed', 'Acknowledged')], default='draft', readonly=True, copy=False, tracking=True)
    document_ids = fields.Many2many('ir.attachment', string='Rental Documents')
    late_days = fields.Integer(readonly=True, copy=False)
    late_charge = fields.Monetary(readonly=True, copy=False)

    @api.depends('inspection_ids.state', 'inspection_ids.kind')
    def _compute_inspections(self):
        for rental in self:
            rental.pickup_inspection_done = bool(rental.inspection_ids.filtered(lambda c: c.kind == 'pickup' and c.state == 'done'))
            rental.return_inspection_done = bool(rental.inspection_ids.filtered(lambda c: c.kind == 'return' and c.state == 'done'))

    def action_inspections(self):
        self.ensure_one()
        return window('Vehicle Inspections', 'car.rental.check', [('rental_id', '=', self.id)], {'default_rental_id': self.id, 'default_kind': 'pickup' if self.status == 'draft' else 'return'})

    def action_pickup_inspection(self):
        self.ensure_one()
        if self.status != 'draft':
            raise ValidationError('Pickup inspections must be completed before starting the rental.')
        return dict(window('Pickup Inspection', 'car.rental.check', context={'default_rental_id': self.id, 'default_kind': 'pickup', 'default_mileage': self.vehicle_id.odometer}), view_mode='form')

    def action_return_inspection(self):
        self.ensure_one()
        if self.status != 'ongoing':
            raise ValidationError('Return inspections are recorded for ongoing rentals.')
        return dict(window('Return Inspection', 'car.rental.check', context={'default_rental_id': self.id, 'default_kind': 'return', 'default_mileage': self.vehicle_id.odometer}), view_mode='form')

    def action_sign_agreement(self):
        for rental in self:
            if rental.status != 'draft' or rental.agreement_state != 'draft':
                raise ValidationError('Only an unsigned draft rental can be acknowledged.')
            if not rental.agreement_terms or not rental.agreement_signature or not rental.agreement_signed_by:
                raise ValidationError('Add approved terms, the customer name and customer signature first.')
            super(Rental, rental).write({'agreement_state': 'signed', 'agreement_signed_on': fields.Datetime.now()})
            rental.message_post(body='Agreement acknowledged by %s.' % rental.agreement_signed_by)

    def write(self, vals):
        if {'status', 'agreement_state', 'agreement_signed_on', 'actual_pickup_datetime', 'actual_return_datetime', 'late_days', 'late_charge'}.intersection(vals):
            raise ValidationError('Use the handover, return or agreement actions to update workflow fields.')
        if {'agreement_terms', 'agreement_signature', 'agreement_signed_by'}.intersection(vals) and any(r.agreement_state == 'signed' for r in self):
            raise ValidationError('An acknowledged agreement is immutable.')
        return super().write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('status', 'draft') != 'draft' or vals.get('agreement_state', 'draft') != 'draft' or any(vals.get(k) for k in ['agreement_signed_on', 'actual_pickup_datetime', 'actual_return_datetime', 'late_charge']):
                raise ValidationError('Create a draft rental and complete the handover workflow.')
            if 'agreement_terms' not in vals:
                company = self.env['car.rental.reservation'].browse(vals.get('reservation_id')).company_id or self.env.company
                vals['agreement_terms'] = company.rental_agreement_terms
        return super().create(vals_list)

    status = fields.Selection(selection_add=[('cancelled', 'Cancelled')], ondelete={'cancelled': 'set default'})

    def _cancel_before_pickup(self):
        self.check_access('write')
        for rental in self:
            self.env.cr.execute('SELECT id FROM car_rental_rental WHERE id=%s FOR UPDATE', [rental.id])
            rental.invalidate_recordset()
            if rental.status == 'cancelled':
                continue
            if rental.status != 'draft':
                raise ValidationError('The vehicle has already been handed over. Use End Rental Early, complete its return inspection, then settle and close the rental.')
            if rental.sudo().invoice_ids.filtered(lambda m: m.state != 'cancel') or rental.sudo().payment_ids or rental.sudo().deposit_transaction_ids:
                raise ValidationError('This booking has financial records. Have Finance settle or cancel its invoices and deposits before cancellation; recorded payments must be retained.')
            if rental.sale_order_id and rental.sale_order_id.state != 'cancel':
                raise ValidationError('Cancel the linked sales quotation/order in Sales first.')
            super(Rental, rental).write({'status': 'cancelled'})
            rental.message_post(body='Booking cancelled before vehicle handover. Agreement and inspection history retained.')

    def action_start_rental(self):
        for rental in self:
            if rental.status != 'draft':
                raise ValidationError('Only draft rentals can be started.')
            rental.vehicle_id._check_ready(handover=True)
            if not rental.pickup_inspection_done or rental.agreement_state != 'signed':
                raise ValidationError('Complete the pickup inspection and acknowledge the agreement before pickup.')
            if rental.deposit_held < rental.reservation_id.deposit_required:
                raise ValidationError('Collect the required security deposit before pickup.')
            if rental.company_id.rental_require_full_payment and rental.balance_due > 0:
                raise ValidationError('Post the rental receipts before pickup, or have management change the payment policy.')
            if self.search_count([('vehicle_id', '=', rental.vehicle_id.id), ('status', '=', 'ongoing'), ('id', '!=', rental.id)]):
                raise ValidationError('The allocated vehicle already has an ongoing rental.')
            if rental.reservation_id.status != 'confirmed':
                raise ValidationError('The reservation must be confirmed.')
            pickup = rental.inspection_ids.filtered(lambda c: c.kind == 'pickup' and c.state == 'done')[:1]
            super(Rental, rental).write({'status': 'ongoing', 'initial_mileage': pickup.mileage, 'actual_pickup_datetime': fields.Datetime.now()})
            rental.vehicle_id._operational_update({'rental_status': 'rented'})

    def action_return_vehicle(self):
        for rental in self:
            if rental.status != 'ongoing' or not rental.return_inspection_done:
                raise ValidationError('Complete the return inspection before returning the vehicle.')
            inspection = rental.inspection_ids.filtered(lambda c: c.kind == 'return' and c.state == 'done')[:1]
            if inspection.mileage < rental.initial_mileage:
                raise ValidationError('Return mileage cannot be below pickup mileage.')
            delay = (inspection.checked_on - rental.expected_return_datetime).total_seconds() / 3600 if rental.expected_return_datetime else 0
            late_days = ceil(max(delay - rental.company_id.rental_late_grace_hours, 0) / 24)
            super(Rental, rental).write({'status': 'returned', 'final_mileage': inspection.mileage, 'actual_return_datetime': inspection.checked_on, 'late_days': late_days, 'late_charge': late_days * rental.reservation_id.quoted_daily_rate})
            rental.vehicle_id._operational_update({'odometer': inspection.mileage, 'rental_status': 'damaged' if inspection.new_damage else 'inspection'})

    def _schedule_once(self, activity, summary, user, deadline):
        if not self.activity_ids.filtered(lambda a: a.activity_type_id == activity and a.summary == summary):
            self.activity_schedule('mail.mail_activity_data_todo', summary=summary, user_id=(user or self.env.user).id, date_deadline=deadline)

    def action_print_agreement(self):
        return self.env.ref('car_rental_management_odoo.report_rental_agreement').report_action(self)


class Inspection(models.Model):
    _name = 'car.rental.check'
    _description = 'Vehicle Pickup and Return Inspection'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'rental_id'
    _order = 'checked_on desc, id desc'

    rental_id = fields.Many2one('car.rental.rental', required=True, ondelete='restrict')
    vehicle_id = fields.Many2one(related='rental_id.vehicle_id', store=True)
    company_id = fields.Many2one(related='rental_id.company_id', store=True)
    kind = fields.Selection([('pickup', 'Pickup'), ('return', 'Return')], required=True, default='pickup')
    checked_on = fields.Datetime(required=True, default=fields.Datetime.now)
    inspector_id = fields.Many2one('res.users', default=lambda self: self.env.user, required=True)
    mileage = fields.Float(required=True)
    fuel_level = fields.Selection([('empty', 'Empty'), ('quarter', 'Quarter'), ('half', 'Half'), ('three_quarters', 'Three quarters'), ('full', 'Full')], required=True)
    exterior = fields.Text(string='Exterior Condition', required=True)
    interior = fields.Text(string='Interior Condition', required=True)
    tyres = fields.Text(string='Tyre Condition', required=True)
    accessories = fields.Text(string='Equipment / Accessories', required=True)
    existing_damage = fields.Text(string='Existing Damage')
    new_damage = fields.Boolean(string='New Damage Identified')
    damage_notes = fields.Text()
    cleaning_required = fields.Boolean(default=True)
    photo_ids = fields.Many2many('ir.attachment', string='Inspection Photographs')
    signature = fields.Image(string='Customer Acknowledgement')
    acknowledged_by = fields.Char(string='Customer Name')
    state = fields.Selection([('draft', 'Draft'), ('done', 'Completed')], default='draft', readonly=True, tracking=True)
    pickup_check_id = fields.Many2one('car.rental.check', compute='_compute_pickup', store=True)
    pickup_fuel = fields.Selection(related='pickup_check_id.fuel_level')
    pickup_exterior = fields.Text(related='pickup_check_id.exterior')
    pickup_interior = fields.Text(related='pickup_check_id.interior')
    pickup_existing_damage = fields.Text(related='pickup_check_id.existing_damage')

    @api.depends('rental_id.inspection_ids.state', 'kind')
    def _compute_pickup(self):
        for check in self:
            check.pickup_check_id = check.rental_id.inspection_ids.filtered(lambda c: c.kind == 'pickup' and c.state == 'done')[:1] if check.kind == 'return' else False

    def action_complete(self):
        for check in self:
            if check.state != 'draft':
                raise ValidationError('This inspection is already completed.')
            if check.kind == 'pickup' and check.rental_id.status != 'draft' or check.kind == 'return' and check.rental_id.status != 'ongoing':
                raise ValidationError('Inspection type does not match the rental stage.')
            required = [
                ('fuel_level', 'Fuel Level'), ('exterior', 'Exterior'),
                ('interior', 'Interior'), ('tyres', 'Tyres'),
                ('accessories', 'Accessories'), ('signature', 'Customer Signature'),
                ('acknowledged_by', 'Acknowledged By (customer name)'),
                ('photo_ids', 'Inspection Photographs'),
            ]
            missing = [label for field, label in required if not check[field] or
                       (isinstance(check[field], str) and not check[field].strip())]
            if missing:
                raise ValidationError('Complete these inspection fields: %s.' % ', '.join(missing))
            minimum = check.vehicle_id.odometer if check.kind == 'pickup' else check.rental_id.initial_mileage
            if check.mileage < minimum:
                raise ValidationError('Inspection mileage cannot be lower than the recorded odometer.')
            if check.checked_on > fields.Datetime.now() + timedelta(minutes=5):
                raise ValidationError('Inspection time cannot be in the future.')
            if self.search_count([('id', '!=', check.id), ('rental_id', '=', check.rental_id.id), ('kind', '=', check.kind), ('state', '=', 'done')]):
                raise ValidationError('A completed inspection of this type already exists for the rental.')
            if check.new_damage and not check.damage_notes:
                raise ValidationError('Describe the new damage.')
            super(Inspection, check).write({'state': 'done', 'inspector_id': self.env.user.id})
            if check.kind == 'pickup':
                check.rental_id.initial_mileage = check.mileage
            elif check.new_damage:
                self.env['car.rental.damage.case'].create({'rental_id': check.rental_id.id, 'inspection_id': check.id, 'name': check.damage_notes})

    @api.model_create_multi
    def create(self, vals_list):
        if any(v.get('state', 'draft') != 'draft' for v in vals_list):
            raise ValidationError('Create draft inspections and use Complete Inspection.')
        return super().create(vals_list)

    def write(self, vals):
        if 'state' in vals or any(c.state == 'done' for c in self) and set(vals) - {'message_follower_ids'}:
            raise ValidationError('Completed inspections cannot be changed.')
        return super().write(vals)

    def unlink(self):
        if any(c.state == 'done' for c in self):
            raise ValidationError('Completed inspections form part of the rental history and cannot be deleted.')
        return super().unlink()


class Damage(models.Model):
    _name = 'car.rental.damage.case'
    _description = 'Vehicle Damage Assessment'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Damage Description', required=True)
    rental_id = fields.Many2one('car.rental.rental', required=True, ondelete='restrict')
    vehicle_id = fields.Many2one(related='rental_id.vehicle_id', store=True)
    company_id = fields.Many2one(related='rental_id.company_id', store=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    inspection_id = fields.Many2one('car.rental.check', required=True)
    cost = fields.Monetary(string='Approved Customer Charge', tracking=True)
    state = fields.Selection([('draft', 'Assessment Pending'), ('approved', 'Charge Approved'), ('repair', 'Under Repair'), ('closed', 'Resolved')], default='draft', readonly=True, tracking=True)
    repair_notes = fields.Text()
    maintenance_id = fields.Many2one('maintenance.request', readonly=True)
    invoice_id = fields.Many2one('account.move', readonly=True, copy=False)
    deposit_retained = fields.Monetary(compute='_compute_settlement')
    additional_charge = fields.Monetary(compute='_compute_settlement')

    @api.depends('rental_id.deposit_transaction_ids.state', 'rental_id.deposit_transaction_ids.amount', 'cost')
    def _compute_settlement(self):
        for damage in self:
            retained = damage.rental_id.deposit_transaction_ids.filtered(lambda d: d.kind == 'retain' and d.state == 'posted' and d.damage_id == damage)
            damage.deposit_retained = sum(retained.mapped('amount'))
            damage.additional_charge = max(damage.cost - damage.deposit_retained, 0)

    def action_approve(self):
        require_role(self.env, 'group_rental_manager')
        for damage in self:
            if damage.state != 'draft' or damage.cost < 0 or damage.inspection_id.rental_id != damage.rental_id or damage.inspection_id.kind != 'return' or damage.inspection_id.state != 'done':
                raise ValidationError('Approve a valid damage assessment linked to the completed return inspection.')
            super(Damage, damage).write({'state': 'approved'})
            damage.vehicle_id.rental_status = 'damaged'

    def action_repair(self):
        require_role(self.env, 'group_fleet_manager')
        for damage in self:
            if damage.state != 'approved':
                raise ValidationError('Approve the damage assessment before requesting repair.')
            request = self.env['maintenance.request'].create({'name': damage.name, 'rental_vehicle_id': damage.vehicle_id.id, 'company_id': damage.company_id.id, 'maintenance_type': 'corrective'})
            super(Damage, damage).write({'state': 'repair', 'maintenance_id': request.id})
            damage.vehicle_id.rental_status = 'maintenance'
        return window('Repair Request', 'maintenance.request', res_id=self[:1].maintenance_id.id)

    def action_close(self):
        require_role(self.env, 'group_fleet_manager')
        for damage in self:
            if damage.state not in ('approved', 'repair') or not damage.repair_notes:
                raise ValidationError('Complete the assessment and record repair/resolution notes.')
            if damage.maintenance_id and not damage.maintenance_id.stage_id.done:
                raise ValidationError('Complete the linked maintenance request first.')
            if damage.cost > 0 and not damage.invoice_id:
                raise ValidationError('Generate the customer damage invoice before closing a chargeable case.')
            super(Damage, damage).write({'state': 'closed'})
            if not damage.vehicle_id.rental_ids.mapped('damage_ids').filtered(lambda d: d.state != 'closed'):
                damage.vehicle_id._operational_update({'rental_status': 'inspection'})

    @api.model_create_multi
    def create(self, vals_list):
        if any(v.get('state', 'draft') != 'draft' or v.get('invoice_id') or v.get('maintenance_id') for v in vals_list):
            raise ValidationError('Create a draft damage assessment first.')
        return super().create(vals_list)

    def write(self, vals):
        if {'state', 'invoice_id', 'maintenance_id'}.intersection(vals):
            raise ValidationError('Use damage workflow actions to update the assessment.')
        if {'cost', 'rental_id', 'inspection_id'}.intersection(vals) and any(d.state != 'draft' for d in self):
            raise ValidationError('Approved damage charges and rental links cannot be changed.')
        return super().write(vals)

    def _schedule_once(self, activity, summary, user, deadline):
        if not self.activity_ids.filtered(lambda a: a.summary == summary):
            self.activity_schedule('mail.mail_activity_data_todo', summary=summary, user_id=(user or self.env.user).id, date_deadline=deadline)


class Maintenance(models.Model):
    _inherit = 'maintenance.request'

    rental_vehicle_id = fields.Many2one('fleet.vehicle', string='Rental Vehicle', check_company=True)
    rental_supplier_id = fields.Many2one('res.partner', string='Service Supplier')
    rental_mileage = fields.Float(string='Service Mileage')
    rental_work = fields.Text(string='Work Performed')
    rental_parts = fields.Text(string='Parts Used')
    rental_labour = fields.Text(string='Labour')
    rental_currency_id = fields.Many2one(related='company_id.currency_id')
    rental_cost = fields.Monetary(currency_field='rental_currency_id', string='Service Cost')
    rental_bill_id = fields.Many2one('account.move', string='Supplier Bill', readonly=True)
    rental_warranty_until = fields.Date(string='Warranty Until')
    rental_next_service_date = fields.Date(string='Next Service Date')
    rental_next_service_mileage = fields.Float(string='Next Service Mileage')

    def action_complete_rental_service(self):
        require_role(self.env, 'group_fleet_manager')
        done = self.env['maintenance.stage'].search([('done', '=', True)], limit=1)
        if not done:
            raise ValidationError('Configure a completed maintenance stage first.')
        for request in self:
            if not request.rental_vehicle_id or not request.rental_work or request.rental_mileage < request.rental_vehicle_id.odometer:
                raise ValidationError('Select the vehicle, record work performed and use valid service mileage.')
            request.stage_id = done
            request.rental_vehicle_id.write({'odometer': request.rental_mileage, 'rental_next_service_mileage': request.rental_next_service_mileage or request.rental_mileage + request.rental_vehicle_id.rental_service_interval, 'rental_next_service_date': request.rental_next_service_date})
            if not request.rental_vehicle_id.rental_ids.mapped('damage_ids').filtered(lambda d: d.state != 'closed'):
                request.rental_vehicle_id.rental_status = 'cleaning'

    @api.constrains('rental_cost', 'rental_mileage')
    def _check_cost(self):
        if any(r.rental_cost < 0 or r.rental_mileage < 0 for r in self):
            raise ValidationError('Maintenance cost and mileage cannot be negative.')
