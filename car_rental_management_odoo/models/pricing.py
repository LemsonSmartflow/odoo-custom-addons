from datetime import datetime, time

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError

from .workflow import window


def require_role(env, role):
    if not env.su and not env.user.has_group('car_rental_management_odoo.' + role):
        raise AccessError('Your Car Rental role does not allow this operation.')


class Category(models.Model):
    _name = 'car.rental.category'
    _description = 'Rental Vehicle Category'

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)


class Destination(models.Model):
    _name = 'car.rental.zone'
    _description = 'Rental Destination'

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    description = fields.Text()
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)


class PricingRule(models.Model):
    _name = 'car.rental.rate.rule'
    _description = 'Destination and Duration Pricing Rule'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'sequence, min_days desc, id'
    _check_company_auto = True

    name = fields.Char(required=True, tracking=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    category_id = fields.Many2one('car.rental.category', required=True, check_company=True)
    destination_id = fields.Many2one('car.rental.zone', required=True, check_company=True)
    min_days = fields.Integer(default=1, required=True)
    max_days = fields.Integer(string='Maximum Days (0 = unlimited)')
    date_from = fields.Date(string='Effective From')
    date_to = fields.Date(string='Effective Until')
    sequence = fields.Integer(string='Priority (lower wins)', default=10)
    daily_rate = fields.Monetary(required=True, tracking=True)
    deposit_ratio = fields.Float(string='Deposit / Daily Rate', default=1, tracking=True,
                                 help='Between 0.5 (50%) and 1 (100%) of the agreed daily rate. Defaults to one full daily rate.')
    deposit_amount = fields.Monetary(string='Security Deposit', compute='_compute_deposit_amount',
                                    inverse='_inverse_deposit_amount',
                                    help='Defaults to the daily rate. Must be between 50% and 100% of the daily rate.')
    state = fields.Selection([('draft', 'Draft'), ('approved', 'Approved'), ('archived', 'Archived')], default='draft', tracking=True)
    notes = fields.Text()
    approved_by = fields.Many2one('res.users', readonly=True, copy=False)

    @api.depends('daily_rate', 'deposit_ratio', 'currency_id')
    def _compute_deposit_amount(self):
        for rule in self:
            rule.deposit_amount = rule.currency_id.round(rule.daily_rate * rule.deposit_ratio)

    def _inverse_deposit_amount(self):
        for rule in self:
            if rule.daily_rate <= 0:
                raise ValidationError('Enter a positive daily rate before setting the security deposit.')
            minimum = rule.currency_id.round(rule.daily_rate * 0.5)
            maximum = rule.currency_id.round(rule.daily_rate)
            if rule.deposit_amount < minimum or rule.deposit_amount > maximum:
                raise ValidationError('Security deposit must be between %s and %s (50%% to 100%% of the daily rate).' % (minimum, maximum))
            rule.deposit_ratio = max(0.5, min(1, rule.deposit_amount / rule.daily_rate))

    @api.onchange('daily_rate')
    def _onchange_daily_rate_deposit(self):
        self.deposit_ratio = 1

    @api.onchange('deposit_amount')
    def _onchange_deposit_amount(self):
        if self.daily_rate > 0:
            self._inverse_deposit_amount()

    @api.constrains('min_days', 'max_days', 'date_from', 'date_to', 'daily_rate', 'deposit_ratio', 'state', 'sequence', 'category_id', 'destination_id')
    def _validate_rule(self):
        for rule in self:
            if rule.min_days < 1 or (rule.max_days and rule.max_days < rule.min_days):
                raise ValidationError('Use a valid rental duration range.')
            if rule.date_from and rule.date_to and rule.date_from > rule.date_to:
                raise ValidationError('The effective end date must follow the start date.')
            if rule.daily_rate <= 0:
                raise ValidationError('Daily rates must be positive.')
            if not 0.5 <= rule.deposit_ratio <= 1:
                raise ValidationError('The security deposit must be between 50% and 100% of the daily rate. Use a ratio from 0.5 to 1.')
            if rule.state == 'approved':
                others = self.search([('id', '!=', rule.id), ('state', '=', 'approved'), ('company_id', '=', rule.company_id.id), ('destination_id', '=', rule.destination_id.id), ('category_id', '=', rule.category_id.id), ('sequence', '=', rule.sequence)])
                for other in others:
                    days_overlap = rule.min_days <= (other.max_days or 10**9) and other.min_days <= (rule.max_days or 10**9)
                    dates_overlap = (rule.date_from or fields.Date.to_date('1900-01-01')) <= (other.date_to or fields.Date.to_date('9999-12-31')) and (other.date_from or fields.Date.to_date('1900-01-01')) <= (rule.date_to or fields.Date.to_date('9999-12-31'))
                    if days_overlap and dates_overlap:
                        raise ValidationError('Approved pricing rules with the same priority cannot overlap.')

    @api.model_create_multi
    def create(self, vals_list):
        require_role(self.env, 'group_rental_manager')
        if any(v.get('state', 'draft') != 'draft' or v.get('approved_by') for v in vals_list):
            raise ValidationError('Create a draft pricing rule, then approve it.')
        return super().create(vals_list)

    def write(self, vals):
        require_role(self.env, 'group_rental_manager')
        if 'daily_rate' in vals and 'deposit_amount' not in vals and 'deposit_ratio' not in vals:
            vals = dict(vals, deposit_ratio=1)
        if 'approved_by' in vals or vals.get('state') == 'approved':
            raise ValidationError('The approval identity is assigned by the approval action.')
        if any(r.state == 'approved' for r in self) and set(vals) - {'state', 'message_follower_ids'}:
            raise ValidationError('Return an approved rate to draft before changing it.')
        return super().write(vals)

    def action_approve(self):
        require_role(self.env, 'group_rental_manager')
        for rule in self:
            super(PricingRule, rule).write({'state': 'approved', 'approved_by': self.env.user.id})

    def action_draft(self):
        require_role(self.env, 'group_rental_manager')
        return super().write({'state': 'draft', 'approved_by': False})


class Reservation(models.Model):
    _name = 'car.rental.reservation'
    _inherit = ['car.rental.reservation', 'mail.thread', 'mail.activity.mixin']
    _check_company_auto = True

    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    destination_id = fields.Many2one('car.rental.zone', check_company=True, tracking=True)
    category_id = fields.Many2one('car.rental.category', check_company=True, tracking=True)
    vehicle_id = fields.Many2one(required=False, check_company=True, tracking=True)
    pricing_rule_id = fields.Many2one('car.rental.rate.rule', readonly=True, copy=False)
    quoted_daily_rate = fields.Float(string='Agreed Daily Rate', readonly=True, copy=False)
    tax_id = fields.Many2one('account.tax', string='Agreed Sales Tax', readonly=True)
    amount_untaxed = fields.Monetary(compute='_compute_amount', store=True)
    tax_amount = fields.Monetary(compute='_compute_amount', store=True)
    standard_daily_rate = fields.Float(readonly=True, copy=False)
    deposit_ratio = fields.Float(readonly=True, copy=False)
    deposit_required = fields.Monetary(compute='_compute_deposit', store=True)
    pricing_note = fields.Char(compute='_compute_pricing_note')
    pickup_datetime = fields.Datetime(string='Scheduled Pickup')
    expected_return_datetime = fields.Datetime(string='Scheduled Return')
    proposed_rate = fields.Float(string='Requested Daily Rate', copy=False)
    override_reason = fields.Text(copy=False)
    override_state = fields.Selection([('none', 'Standard Rate'), ('pending', 'Approval Pending'), ('approved', 'Override Approved')], default='none', readonly=True, tracking=True, copy=False)
    override_approved_by = fields.Many2one('res.users', readonly=True, copy=False)
    override_approved_on = fields.Datetime(readonly=True, copy=False)
    legacy_booking = fields.Boolean(readonly=True, copy=False)
    available_vehicle_ids = fields.Many2many('car.rental.vehicle', compute='_compute_available')

    @api.depends('quoted_daily_rate', 'deposit_ratio')
    def _compute_deposit(self):
        for record in self:
            record.deposit_required = record.quoted_daily_rate * record.deposit_ratio

    @api.depends('number_of_days', 'quoted_daily_rate', 'tax_id')
    def _compute_amount(self):
        for record in self:
            subtotal = record.number_of_days * record.quoted_daily_rate
            if record.tax_id:
                totals = record.tax_id.compute_all(record.quoted_daily_rate, currency=record.currency_id, quantity=record.number_of_days)
                record.amount_untaxed = totals['total_excluded']
                record.amount = totals['total_included']
            else:
                record.amount_untaxed = subtotal
                record.amount = subtotal
            record.tax_amount = record.amount - record.amount_untaxed

    @api.depends('destination_id', 'category_id', 'start_date', 'end_date', 'pricing_rule_id')
    def _compute_pricing_note(self):
        for record in self:
            record.pricing_note = 'Approved pricing rule selected' if record.pricing_rule_id else 'Select destination, category and dates. An approved pricing rule is required.'

    def _rate(self):
        self.ensure_one()
        if not (self.destination_id and self.category_id and self.start_date and self.number_of_days > 0):
            return self.env['car.rental.rate.rule']
        return self.env['car.rental.rate.rule'].search([
            ('company_id', '=', self.company_id.id), ('state', '=', 'approved'),
            ('destination_id', '=', self.destination_id.id), ('category_id', '=', self.category_id.id),
            ('min_days', '<=', self.number_of_days), '|', ('max_days', '=', 0), ('max_days', '>=', self.number_of_days),
            '|', ('date_from', '=', False), ('date_from', '<=', self.start_date),
            '|', ('date_to', '=', False), ('date_to', '>=', self.start_date),
        ], limit=1)

    def _price_values(self):
        rule = self._rate()
        return {'pricing_rule_id': rule.id or False, 'standard_daily_rate': rule.daily_rate or 0,
                'quoted_daily_rate': rule.daily_rate or 0, 'deposit_ratio': rule.deposit_ratio or 0,
                'tax_id': self.company_id.cr_tax_id.id, 'override_state': 'none', 'override_approved_by': False, 'override_approved_on': False}

    @api.onchange('destination_id', 'category_id', 'start_date', 'end_date')
    def _onchange_pricing(self):
        if self.status == 'draft':
            self.update(self._price_values())

    @api.onchange('vehicle_id')
    def _onchange_vehicle_category(self):
        if self.vehicle_id:
            self.category_id = self.vehicle_id.category_id
        self._onchange_pricing()

    @api.depends('category_id', 'start_date', 'end_date', 'company_id')
    def _compute_available(self):
        for record in self:
            candidates = self.env['car.rental.vehicle'].search([
                ('company_id', '=', record.company_id.id), ('category_id', '=', record.category_id.id),
                ('status', 'in', ['available', 'reserved', 'rented']), ('registration_number', '!=', False),
            ]) if record.category_id else self.env['car.rental.vehicle']
            conflicts = self.search([('id', '!=', record._origin.id or 0), ('vehicle_id', 'in', candidates.ids), ('status', '!=', 'cancelled'), ('start_date', '<', record.end_date), ('end_date', '>', record.start_date)]) if record.start_date and record.end_date else self.browse()
            record.available_vehicle_ids = candidates - conflicts.mapped('vehicle_id')

    @api.model_create_multi
    def create(self, vals_list):
        protected = {'legacy_booking', 'override_approved_by', 'override_approved_on', 'tax_id'}
        for vals in vals_list:
            if protected.intersection(vals) or vals.get('override_state', 'none') != 'none':
                raise ValidationError('Approval and legacy fields cannot be assigned manually.')
            if vals.get('status', 'draft') != 'draft':
                raise ValidationError('Create a draft reservation, then confirm it.')
            vals.pop('quoted_daily_rate', None)
            if not vals.get('category_id') and vals.get('vehicle_id'):
                vals['category_id'] = self.env['car.rental.vehicle'].browse(vals['vehicle_id']).category_id.id
            if vals.get('start_date') and not vals.get('pickup_datetime'):
                vals['pickup_datetime'] = datetime.combine(fields.Date.to_date(vals['start_date']), time(8))
            if vals.get('end_date') and not vals.get('expected_return_datetime'):
                vals['expected_return_datetime'] = datetime.combine(fields.Date.to_date(vals['end_date']), time(8))
        records = super().create(vals_list)
        for record in records:
            super(Reservation, record).write(record._price_values())
        return records

    def write(self, vals):
        protected = {'quoted_daily_rate', 'standard_daily_rate', 'pricing_rule_id', 'deposit_ratio', 'legacy_booking', 'override_state', 'override_approved_by', 'override_approved_on', 'tax_id'}
        if protected.intersection(vals) or 'status' in vals:
            raise ValidationError('Use pricing and approval actions to change the agreed rate.')
        if {'proposed_rate', 'override_reason'}.intersection(vals) and any(r.status != 'draft' or r.override_state == 'approved' for r in self):
            raise ValidationError('Reprice an unused draft reservation before changing its approved override.')
        if 'start_date' in vals and 'pickup_datetime' not in vals:
            vals['pickup_datetime'] = datetime.combine(fields.Date.to_date(vals['start_date']), time(8))
        if 'end_date' in vals and 'expected_return_datetime' not in vals:
            vals['expected_return_datetime'] = datetime.combine(fields.Date.to_date(vals['end_date']), time(8))
        if {'destination_id', 'category_id', 'start_date', 'end_date', 'vehicle_id', 'pickup_datetime', 'expected_return_datetime'}.intersection(vals) and any(r.status != 'draft' for r in self):
            raise ValidationError('Confirmed booking details are locked. Cancel an unused reservation and create a new one.')
        result = super().write(vals)
        if {'destination_id', 'category_id', 'start_date', 'end_date', 'vehicle_id'}.intersection(vals):
            for record in self:
                super(Reservation, record).write(record._price_values())
        return result

    def action_allocate(self):
        self.ensure_one()
        if self.status != 'draft':
            raise ValidationError('Allocate a vehicle while the reservation is in draft.')
        self._compute_available()
        if not self.available_vehicle_ids:
            raise ValidationError('No vehicle in this category is available for the requested dates.')
        self.vehicle_id = self.available_vehicle_ids.sorted('fleet_id')[:1]

    def action_confirm(self):
        for record in self:
            if record.status != 'draft':
                raise ValidationError('Only draft reservations can be confirmed.')
            if not record.destination_id or not record.category_id:
                raise ValidationError('Select the destination and vehicle category.')
            if record.override_state == 'pending':
                raise ValidationError('A manager must approve the requested rate first.')
            if record.override_state != 'approved':
                super(Reservation, record).write(record._price_values())
            if not record.pricing_rule_id or record.quoted_daily_rate <= 0:
                raise ValidationError('No approved pricing rule matches this destination, category, duration and date.')
            if not record.vehicle_id:
                record.action_allocate()
            if record.vehicle_id.category_id != record.category_id:
                raise ValidationError('The allocated vehicle does not match the requested category.')
            record.vehicle_id._check_ready()
            record._check_vehicle_availability()
            record._check_driving_license()
            super(Reservation, record).write({'status': 'confirmed'})
            record.vehicle_id._refresh_reserved_status()

    def action_cancel(self):
        vehicles = self.mapped('vehicle_id')
        for record in self:
            super(Reservation, record).write({'status': 'cancelled'})
        vehicles._refresh_reserved_status()

    def action_reset_draft(self):
        vehicles = self.mapped('vehicle_id')
        for record in self:
            super(Reservation, record).write({'status': 'draft'})
        vehicles._refresh_reserved_status()

    @api.constrains('vehicle_id', 'start_date', 'end_date', 'status')
    def _check_vehicle_availability(self):
        for record in self:
            if record.status == 'cancelled' or not record.vehicle_id or not record.start_date or not record.end_date:
                continue
            self.env.cr.execute('UPDATE car_rental_vehicle SET id = id WHERE id = %s', [record.vehicle_id.id])
            if self.search_count([('id', '!=', record.id), ('vehicle_id', '=', record.vehicle_id.id), ('status', '!=', 'cancelled'), ('start_date', '<', record.end_date), ('end_date', '>', record.start_date)]):
                raise ValidationError('This vehicle is already allocated during these dates.')

    def action_request_override(self):
        for record in self:
            if record.status != 'draft' or record.proposed_rate <= 0 or not record.override_reason:
                raise ValidationError('Provide a positive proposed rate and a reason on a draft reservation.')
            if not record.pricing_rule_id:
                raise ValidationError('An approved standard rate is required before requesting an override.')
            super(Reservation, record).write({'override_state': 'pending'})
            record.message_post(body='Rate override requested: %s → %s. Reason: %s' % (record.standard_daily_rate, record.proposed_rate, record.override_reason))

    def action_approve_override(self):
        require_role(self.env, 'group_rental_manager')
        for record in self:
            if record.status != 'draft' or record.override_state != 'pending' or record.proposed_rate <= 0:
                raise ValidationError('Only a pending override on a draft booking can be approved.')
            super(Reservation, record).write({'quoted_daily_rate': record.proposed_rate, 'override_state': 'approved', 'override_approved_by': self.env.user.id, 'override_approved_on': fields.Datetime.now()})
            record.message_post(body='Rate override approved at %s per day.' % record.proposed_rate)

    def action_reprice(self):
        for record in self:
            if record.status != 'draft':
                raise ValidationError('Only draft bookings can be repriced.')
            super(Reservation, record).write(record._price_values())

    @api.constrains('pickup_datetime', 'expected_return_datetime', 'start_date', 'end_date')
    def _check_times(self):
        for record in self:
            if record.pickup_datetime and record.expected_return_datetime and record.expected_return_datetime <= record.pickup_datetime:
                raise ValidationError('Scheduled return must follow scheduled pickup.')
            if record.pickup_datetime and record.start_date and record.pickup_datetime.date() != record.start_date:
                raise ValidationError('Scheduled pickup must fall on the rental start date (UTC).')
            if record.expected_return_datetime and record.end_date and record.expected_return_datetime.date() != record.end_date:
                raise ValidationError('Scheduled return must fall on the rental end date (UTC).')


class Customer(models.Model):
    _name = 'car.rental.customer'
    _inherit = ['car.rental.customer', 'mail.thread', 'mail.activity.mixin']

    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    partner_id = fields.Many2one('res.partner', string='Accounting Contact', readonly=True, copy=False)
    document_ids = fields.Many2many('ir.attachment', string='ID and Licence Documents')

    @api.model_create_multi
    def create(self, vals_list):
        if any(v.get('partner_id') for v in vals_list):
            raise ValidationError('Accounting contacts are created through the invoicing workflow.')
        return super().create(vals_list)

    def _ensure_partner(self):
        for customer in self:
            vals = {'name': customer.display_name, 'email': customer.email, 'phone': customer.phone, 'street': customer.address, 'company_id': customer.company_id.id}
            if not customer.partner_id:
                super(Customer, customer).write({'partner_id': self.env['res.partner'].create(vals).id})
            else:
                customer.partner_id.write(vals)
        return self.partner_id

    def write(self, vals):
        if 'partner_id' in vals:
            raise ValidationError('The accounting contact is managed by the invoicing workflow.')
        return super().write(vals)
