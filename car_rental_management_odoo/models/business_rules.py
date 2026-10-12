"""Rental eligibility, monthly references and connected operational defaults."""
from math import ceil

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from .pricing import require_role
from .workflow import window


def monthly_reference(env, model, prefix, company, date):
    date = fields.Date.to_date(date)
    code = '%s.%s.%s' % (model, company.id, date.strftime('%Y.%m'))
    # Serialize creation of a month's sequence; only this internal sequence is sudoed.
    env.cr.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', [code])
    sequence = env['ir.sequence'].sudo().search([('code', '=', code), ('company_id', '=', company.id)], limit=1)
    if not sequence:
        sequence = env['ir.sequence'].sudo().create({
            'name': '%s %s' % (prefix, date.strftime('%Y-%m')),
            'code': code, 'company_id': company.id, 'padding': 3,
            'prefix': '%s %s ' % (prefix, date.strftime('%b').upper()),
        })
    while True:
        reference = sequence.next_by_id()
        if not reference:
            raise ValidationError('Monthly reference numbering is not configured correctly.')
        if not env[model].sudo().search_count([('company_id', '=', company.id), ('reference', '=ilike', reference)]):
            return reference


def validate_reference(records):
    for record in records:
        if not record.reference or not record.reference.strip() or record.reference.strip().lower() == 'new':
            raise ValidationError('Enter a reference or use the automatically generated reference.')
        key = '%s:%s:%s' % (record._name, record.company_id.id, record.reference.strip().lower())
        record.env.cr.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', [key])
        if record.sudo().search_count([('id', '!=', record.id), ('company_id', '=', record.company_id.id), ('reference', '=ilike', record.reference)]):
            raise ValidationError('This reference is already used in the company. Choose a different reference.')


class Customer(models.Model):
    _inherit = 'car.rental.customer'

    cin = fields.Char(string='Omang / Passport Number')
    physical_address = fields.Text(required=True)
    postal_address = fields.Text(required=True)
    date_of_birth = fields.Date(required=True)
    license_issue_date = fields.Date(string='Licence Date of Issue', required=True)
    omang_document_ids = fields.Many2many('ir.attachment', 'rental_customer_omang_rel', string='Omang Documents')
    passport_document_ids = fields.Many2many('ir.attachment', 'rental_customer_passport_rel', string='Passport Documents')
    license_document_ids = fields.Many2many('ir.attachment', 'rental_customer_licence_rel', string='Licence Documents')

    @api.constrains('physical_address', 'postal_address', 'date_of_birth', 'license_issue_date', 'license_expiry')
    def _check_profile(self):
        for customer in self:
            if not customer.physical_address or not customer.physical_address.strip() or not customer.postal_address or not customer.postal_address.strip():
                raise ValidationError('Physical address and postal address are required.')
            if customer.date_of_birth and customer.date_of_birth >= fields.Date.today():
                raise ValidationError('Date of birth must be in the past.')
            if customer.license_issue_date and customer.license_expiry and customer.license_issue_date > customer.license_expiry:
                raise ValidationError('Licence expiry must follow its issue date.')
            if customer.license_issue_date and customer.license_issue_date > fields.Date.today():
                raise ValidationError('Licence date of issue cannot be in the future.')

    def _check_rental_eligibility(self, pickup, return_time):
        self.ensure_one()
        local_pickup = fields.Datetime.context_timestamp(self, pickup).date()
        local_return = fields.Datetime.context_timestamp(self, return_time).date()
        if not all([self.physical_address, self.postal_address, self.date_of_birth, self.license_issue_date]):
            raise ValidationError('Complete the customer addresses, date of birth and licence issue date before booking.')
        birthday = self.date_of_birth
        age = local_pickup.year - birthday.year - ((local_pickup.month, local_pickup.day) < (birthday.month, birthday.day))
        if age < 21:
            raise ValidationError('The customer must be at least 21 years old on the pickup date.')
        if not self.license_expiry or self.license_expiry < local_return or self.license_issue_date > local_pickup:
            raise ValidationError('The driving licence must be valid throughout the rental period.')
        if not (self.omang_document_ids or self.passport_document_ids) or not self.license_document_ids:
            raise ValidationError('Upload either Omang or passport, plus the driving licence, before confirming the reservation.')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals['address'] = vals.get('physical_address') or vals.get('address')
        return super().create(vals_list)

    def write(self, vals):
        if 'physical_address' in vals:
            vals = dict(vals, address=vals['physical_address'])
        return super().write(vals)


class Vehicle(models.Model):
    _inherit = 'car.rental.vehicle'

    @api.onchange('fleet_id')
    def _onchange_fleet_registration(self):
        self.registration_number = self.fleet_id

    @api.onchange('registration_number')
    def _onchange_registration_fleet(self):
        self.fleet_id = self.registration_number

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('fleet_id') or vals.get('registration_number'):
                value = vals.get('fleet_id') or vals['registration_number']
                if vals.get('fleet_id') and vals.get('registration_number') and vals['fleet_id'] != vals['registration_number']:
                    raise ValidationError('Fleet ID and registration number must be the same.')
                vals.update(fleet_id=value, registration_number=value)
        return super().create(vals_list)

    def write(self, vals):
        if 'fleet_id' in vals or 'registration_number' in vals:
            value = vals.get('fleet_id', vals.get('registration_number'))
            if 'fleet_id' in vals and 'registration_number' in vals and vals['fleet_id'] != vals['registration_number']:
                raise ValidationError('Fleet ID and registration number must be the same.')
            vals = dict(vals, fleet_id=value, registration_number=value)
        return super().write(vals)


class PricingRule(models.Model):
    _inherit = 'car.rental.rate.rule'

    cleaning_fee = fields.Monetary(string='Dirty Return Cleaning Fee', default=0, tracking=True,
                                   help='Charge for a dirty return. Set a positive amount before hiring vehicles under this rule.')

    @api.constrains('cleaning_fee')
    def _check_cleaning_fee(self):
        if any(rule.cleaning_fee < 0 for rule in self):
            raise ValidationError('The cleaning fee cannot be negative.')


class Reservation(models.Model):
    _inherit = 'car.rental.reservation'
    _order = 'pickup_datetime desc, id desc'

    cleaning_fee = fields.Monetary(string='Agreed Dirty Return Fee', readonly=True, copy=False)
    reference = fields.Char(default=False, required=True, copy=False, tracking=True)

    @api.constrains('reference', 'company_id')
    def _check_reference(self):
        validate_reference(self)

    @api.depends('pickup_datetime', 'expected_return_datetime')
    def _compute_number_of_days(self):
        for record in self:
            seconds = (record.expected_return_datetime - record.pickup_datetime).total_seconds() if record.pickup_datetime and record.expected_return_datetime else 0
            record.number_of_days = ceil(seconds / 86400) if seconds > 0 else 0

    @api.constrains('pickup_datetime', 'expected_return_datetime')
    def _check_dates(self):
        for record in self:
            if record.pickup_datetime and record.expected_return_datetime and record.expected_return_datetime <= record.pickup_datetime:
                raise ValidationError('Return date and time must be after pickup date and time.')

    @api.onchange('pickup_datetime', 'expected_return_datetime')
    def _onchange_booking_times(self):
        self.start_date = self.pickup_datetime.date() if self.pickup_datetime else False
        self.end_date = self.expected_return_datetime.date() if self.expected_return_datetime else False
        self._onchange_pricing()

    @api.depends('category_id', 'pickup_datetime', 'expected_return_datetime', 'company_id')
    def _compute_available(self):
        for record in self:
            candidates = self.env['car.rental.vehicle'].search([
                ('company_id', '=', record.company_id.id), ('category_id', '=', record.category_id.id),
                ('status', 'in', ['available', 'reserved', 'rented']), ('registration_number', '!=', False),
            ]) if record.category_id else self.env['car.rental.vehicle']
            conflicts = self.search([('id', '!=', record._origin.id or 0), ('vehicle_id', 'in', candidates.ids),
                                     ('status', '!=', 'cancelled'), ('pickup_datetime', '<', record.expected_return_datetime),
                                     ('expected_return_datetime', '>', record.pickup_datetime)]) if record.pickup_datetime and record.expected_return_datetime else self.browse()
            record.available_vehicle_ids = candidates - conflicts.mapped('vehicle_id')

    @api.constrains('vehicle_id', 'pickup_datetime', 'expected_return_datetime', 'status')
    def _check_vehicle_availability(self):
        for record in self:
            if record.status == 'cancelled' or not record.vehicle_id or not record.pickup_datetime or not record.expected_return_datetime:
                continue
            self.env.cr.execute('UPDATE car_rental_vehicle SET id = id WHERE id = %s', [record.vehicle_id.id])
            if self.search_count([('id', '!=', record.id), ('vehicle_id', '=', record.vehicle_id.id), ('status', '!=', 'cancelled'),
                                  ('pickup_datetime', '<', record.expected_return_datetime), ('expected_return_datetime', '>', record.pickup_datetime)]):
                raise ValidationError('This vehicle is already allocated during these pickup/return times.')

    def _price_values(self):
        values = super()._price_values()
        values['cleaning_fee'] = self._rate().cleaning_fee or 0
        return values

    @staticmethod
    def _sync_times(vals):
        for source, target in [('pickup_datetime', 'start_date'), ('expected_return_datetime', 'end_date')]:
            if vals.get(source):
                vals[target] = fields.Datetime.to_datetime(vals[source]).date()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if {'deposit_required', 'deposit_ratio', 'cleaning_fee'}.intersection(vals):
                raise ValidationError('Deposits and cleaning fees are calculated from the approved pricing rule.')
            self._sync_times(vals)
            vals['reference'] = (vals.get('reference') or '').strip()
            if not vals['reference'] or vals['reference'].lower() == 'new':
                company = self.env['res.company'].browse(vals.get('company_id')) or self.env.company
                date = vals.get('start_date') or fields.Date.context_today(self)
                vals['reference'] = monthly_reference(self.env, self._name, 'RES', company, date)
        return super().create(vals_list)

    def write(self, vals):
        if {'deposit_required', 'deposit_ratio', 'cleaning_fee'}.intersection(vals):
            raise ValidationError('Deposits and cleaning fees are calculated from the approved pricing rule.')
        vals = dict(vals)
        if 'reference' in vals:
            vals['reference'] = (vals['reference'] or '').strip()
        self._sync_times(vals)
        return super().write(vals)

    @api.constrains('quoted_daily_rate', 'deposit_ratio', 'status')
    def _check_deposit_policy(self):
        for record in self:
            if record.status == 'confirmed' and (not 0.5 <= record.deposit_ratio <= 1 or record.deposit_required < record.quoted_daily_rate * 0.5 - 0.005):
                raise ValidationError('A confirmed reservation must hold a deposit of at least 50% of its agreed daily rate.')

    def action_confirm(self):
        for record in self:
            if not record.pickup_datetime or not record.expected_return_datetime:
                raise ValidationError('Select pickup and return date and time.')
            record.customer_id._check_rental_eligibility(record.pickup_datetime, record.expected_return_datetime)
        return super().action_confirm()

    def action_refresh_cleaning_fee(self):
        require_role(self.env, 'group_rental_manager')
        for record in self:
            if record.status != 'confirmed' or any(r.status != 'draft' or r.agreement_state == 'signed' for r in record.rental_ids):
                raise ValidationError('Update the cleaning fee before signing the agreement or handing over the vehicle.')
            if record.pricing_rule_id.state != 'approved' or record.pricing_rule_id.cleaning_fee <= 0:
                raise ValidationError('Set and approve a positive cleaning fee on the linked pricing rule first.')
            super(Reservation, record).write({'cleaning_fee': record.pricing_rule_id.cleaning_fee})
            record.message_post(body='Cleaning fee updated from the approved pricing rule before agreement signature: %s.' % record.cleaning_fee)


class Rental(models.Model):
    _inherit = 'car.rental.rental'
    _order = 'id desc'

    pickup_datetime = fields.Datetime(related='reservation_id.pickup_datetime', string='Pickup Date and Time', store=True)
    cleaning_charge = fields.Monetary(readonly=True, copy=False)
    reference = fields.Char(default=False, required=True, copy=False, tracking=True)

    @api.constrains('reference', 'company_id')
    def _check_reference(self):
        validate_reference(self)

    @api.onchange('reservation_id')
    def _onchange_customer_signature_name(self):
        self.agreement_signed_by = self.customer_id.display_name if self.customer_id else False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'deposit_required' in vals or 'cleaning_charge' in vals:
                raise ValidationError('Use the rental workflow to calculate deposits and charges.')
            reservation = self.env['car.rental.reservation'].browse(vals.get('reservation_id'))
            vals['reference'] = (vals.get('reference') or '').strip()
            if reservation:
                vals.setdefault('agreement_signed_by', reservation.customer_id.display_name)
                if not vals['reference'] or vals['reference'].lower() == 'new':
                    vals['reference'] = monthly_reference(self.env, self._name, 'REN', reservation.company_id, reservation.start_date)
        return super().create(vals_list)

    def write(self, vals):
        if {'deposit_required', 'cleaning_charge'}.intersection(vals):
            raise ValidationError('Use the rental workflow to calculate deposits and charges.')
        if 'reference' in vals:
            vals = dict(vals, reference=(vals['reference'] or '').strip())
        return super().write(vals)

    def action_start_rental(self):
        for rental in self:
            rental.reservation_id._check_deposit_policy()
            rental.customer_id._check_rental_eligibility(rental.reservation_id.pickup_datetime, rental.expected_return_datetime)
        result = super().action_start_rental()
        for rental in self:
            pickup = rental.inspection_ids.filtered(lambda c: c.kind == 'pickup' and c.state == 'done')[:1]
            # Internal write keeps the recorded inspection's actual handover time.
            rental._operational_handover_time(pickup.checked_on)
        return result

    def _operational_handover_time(self, date):
        # Implemented via the original Rental class's parent to retain public guards.
        from .operations import Rental as OperationalRental
        super(OperationalRental, self).write({'actual_pickup_datetime': date})

    def action_return_vehicle(self):
        for rental in self:
            check = rental.inspection_ids.filtered(lambda c: c.kind == 'return' and c.state == 'done')[:1]
            if check and check.clean == 'no' and rental.reservation_id.cleaning_fee <= 0:
                raise ValidationError('Configure a positive dirty-return fee in the booking pricing rule before completing this return.')
        result = super().action_return_vehicle()
        from .operations import Rental as OperationalRental
        for rental in self:
            check = rental.inspection_ids.filtered(lambda c: c.kind == 'return' and c.state == 'done')[:1]
            charge = rental.reservation_id.cleaning_fee if check.clean == 'no' else 0
            super(OperationalRental, rental).write({'cleaning_charge': charge})
            if charge:
                rental.sudo().action_cleaning_invoice()
        return result

    def action_cleaning_invoice(self):
        self.ensure_one()
        require_role(self.env, 'group_rental_accountant')
        if self.status != 'returned' or self.cleaning_charge <= 0:
            raise ValidationError('Cleaning charges require a completed dirty return.')
        invoice = self.invoice_ids.filtered(lambda m: m.rental_invoice_kind == 'cleaning' and m.state != 'cancel')[:1]
        if not invoice:
            invoice = self._make_invoice('cleaning', self.company_id.cr_income_account_id,
                                         [{'name': 'Dirty return cleaning: ' + self.reference, 'quantity': 1, 'price_unit': self.cleaning_charge}])
        return window('Cleaning Invoice', 'account.move', res_id=invoice.id)

    def action_apply_cleaning_deposit(self):
        self.ensure_one()
        require_role(self.env, 'group_rental_accountant')
        invoice = self.invoice_ids.filtered(lambda m: m.rental_invoice_kind == 'cleaning' and m.state == 'posted' and m.amount_residual > 0)[:1]
        if not invoice:
            raise ValidationError('Post the cleaning invoice before applying the security deposit.')
        return dict(self.action_deposits(), view_mode='form', target='new', context={
            'default_rental_id': self.id, 'default_kind': 'retain', 'default_charge_invoice_id': invoice.id,
            'default_amount': min(self.deposit_held, invoice.amount_residual)})


class Inspection(models.Model):
    _inherit = 'car.rental.check'

    clean = fields.Selection([('yes', 'Yes'), ('no', 'No')], string='Clean?', required=True, default='yes')
    fuel_level = fields.Selection(selection_add=[('blinking', 'Blinking Bar')] +
                                  [('bar_%s' % i, '%s Bar%s' % (i, '' if i == 1 else 's')) for i in range(1, 9)],
                                  ondelete={key: 'set empty' for key in ['blinking'] + ['bar_%s' % i for i in range(1, 9)]})

    @api.onchange('rental_id')
    def _onchange_acknowledgement_name(self):
        self.acknowledged_by = self.rental_id.customer_id.display_name if self.rental_id else False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('rental_id'):
                rental = self.env['car.rental.rental'].browse(vals['rental_id'])
                vals.setdefault('acknowledged_by', rental.customer_id.display_name)
        return super().create(vals_list)

    def action_complete(self):
        for check in self:
            if not check.clean:
                raise ValidationError('Select whether the vehicle is clean: Yes or No.')
        return super().action_complete()


class Move(models.Model):
    _inherit = 'account.move'
    rental_invoice_kind = fields.Selection(selection_add=[('cleaning', 'Cleaning')])


class Deposit(models.Model):
    _inherit = 'car.rental.deposit.transaction'
    charge_invoice_id = fields.Many2one('account.move', string='Cleaning Invoice', check_company=True)

    def action_post(self):
        for event in self:
            if event.kind == 'collect' and event.rental_id.deposit_collected <= 0 and event.amount < event.rental_id.reservation_id.quoted_daily_rate * 0.5 - 0.005:
                raise ValidationError('Initial security deposit collection cannot be below 50% of the agreed daily rate.')
        return super().action_post()
