"""A resumable booking workspace. Operational records remain authoritative."""
from datetime import timedelta
from math import ceil

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from .workflow import window
from .pricing import require_role


class Journey(models.Model):
    _name = 'car.rental.journey'
    _description = 'Booking'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'
    _check_company_auto = True
    _reservation_unique = models.Constraint('UNIQUE(reservation_id)', 'This reservation already has a booking.')

    name = fields.Char(compute='_compute_progress')
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    partner_id = fields.Many2one('res.partner', string='Customer', check_company=True)
    destination_id = fields.Many2one('car.rental.zone', check_company=True)
    category_id = fields.Many2one('fleet.vehicle.model.category')
    vehicle_id = fields.Many2one('fleet.vehicle', check_company=True)
    pickup_datetime = fields.Datetime()
    expected_return_datetime = fields.Datetime(string='Return Date and Time')
    number_of_days = fields.Integer(string='Rental Days (24-hour periods)', default=1)
    reservation_id = fields.Many2one('car.rental.reservation', readonly=True, copy=False, check_company=True)
    rental_id = fields.Many2one('car.rental.rental', compute='_compute_progress')
    cancelled = fields.Boolean(readonly=True, copy=False)
    details_started = fields.Boolean(copy=False)
    currency_id = fields.Many2one(related='company_id.currency_id')
    amount = fields.Float(related='reservation_id.amount')
    deposit_required = fields.Monetary(related='reservation_id.deposit_required')
    customer_deposit_credit = fields.Monetary(
        compute='_compute_customer_deposit_credit', string='Customer Deposit Credit Available')
    cleaning_fee = fields.Monetary(related='reservation_id.cleaning_fee')
    vehicle_image = fields.Image(related='vehicle_id.rental_image')
    guidance = fields.Text(compute='_compute_progress')
    step = fields.Selection([(s, label) for s, label in [
        ('customer', '1 Customer'), ('details', '2 Booking'), ('quote', '3 Quote'),
        ('confirm', '4 Confirm'), ('agreement', '5 Agreement'), ('payment', '6 Payment'), ('pickup', '7 Pickup Inspection'),
        ('handover', '8 Handover'), ('return', '9 Return'), ('settlement', '10 Settlement'),
        ('closed', '11 Closed'), ('cancelled', 'Cancelled')]], compute='_compute_progress')

    @api.depends('partner_id', 'company_id')
    def _compute_customer_deposit_credit(self):
        Rentals = self.env['car.rental.rental']
        for journey in self:
            sources = Rentals._deposit_credit_sources(journey.partner_id, journey.company_id)
            journey.customer_deposit_credit = sum(sources.mapped('deposit_held'))

    @api.depends('cancelled', 'partner_id', 'details_started', 'reservation_id.status', 'reservation_id.reference',
                 'reservation_id.rental_ids.status', 'reservation_id.rental_ids.agreement_state',
                 'reservation_id.rental_ids.inspection_ids.state', 'reservation_id.rental_ids.deposit_held',
                 'reservation_id.rental_ids.balance_due', 'reservation_id.rental_ids.invoice_ids.state',
                 'reservation_id.rental_ids.invoice_ids.amount_residual', 'reservation_id.rental_ids.sale_order_id')
    def _compute_progress(self):
        for journey in self:
            reservation = journey.reservation_id
            rental = reservation.rental_ids[:1]
            journey.rental_id = rental
            journey.name = reservation.reference or ('Booking: %s' % journey.partner_id.display_name if journey.partner_id else 'New Booking')
            step, guidance = 'customer', 'Select or create the customer. Complete identity, licence and address details.'
            if journey.details_started:
                step, guidance = 'details', 'Choose destination and category, set pickup date/time and rental days. The return time is calculated in 24-hour periods.'
            if reservation:
                step, guidance = 'quote', 'Review the calculated hire price, refundable deposit and one-time dirty return fee. Open the reservation for changes or a manager-approved rate override.'
            if reservation.status == 'confirmed':
                step, guidance = 'confirm', 'The reservation is confirmed. Continue to open or create its rental.'
            if rental:
                step, guidance = 'agreement', 'Complete the rental agreement before collecting payment. For a digital agreement, collect all six signatures, then return here and continue.'
                if rental.agreement_state == 'signed':
                    step, guidance = 'payment', 'Finance: post the rental invoice, record payment under company policy, and collect the full required security deposit.'
                    if not rental._journey_payment_blockers():
                        step, guidance = 'pickup', 'Complete the pickup inspection, including photographs and customer signature.'
                        if rental.pickup_inspection_done:
                            step, guidance = 'handover', 'Ready for final handover checks. Continue to hand over the vehicle; compliance and availability are checked again.'
                if rental.status == 'ongoing':
                    step, guidance = 'return', 'Vehicle is on hire. Record the actual return inspection with time, mileage, fuel, cleanliness and any damage. Continue after completing it.'
                if rental.status == 'returned':
                    step, guidance = 'settlement', '\n'.join(rental._journey_close_blockers()) or 'All customer balances and deposit movements are settled. Continue to close the rental. Fleet release remains a separate task.'
                if rental.status == 'closed':
                    step, guidance = 'closed', 'Booking cycle complete. Fleet cleaning, repairs and release remain available from the vehicle record.'
            if journey.cancelled or reservation.status == 'cancelled':
                step, guidance = 'cancelled', 'This reservation was cancelled. Use Create a Booking to start a new booking.'
            journey.step, journey.guidance = step, guidance

    def write(self, vals):
        if 'cancelled' in vals:
            raise ValidationError('Use Cancel Booking to cancel this booking.')
        if 'reservation_id' in vals:
            raise ValidationError('Use Continue to link the reservation.')
        duration_fields = {'pickup_datetime', 'expected_return_datetime', 'number_of_days'}
        if ({'partner_id', 'company_id', 'destination_id', 'category_id', 'vehicle_id'} | duration_fields).intersection(vals) and any(self.mapped('reservation_id')):
            raise ValidationError('Edit the linked reservation to change booking details.')
        if duration_fields.intersection(vals):
            return_value = True
            for journey in self:
                journey_vals = dict(vals)
                pickup = fields.Datetime.to_datetime(journey_vals['pickup_datetime']) if journey_vals.get('pickup_datetime') else (
                    journey.pickup_datetime if 'pickup_datetime' not in journey_vals else False)
                if 'number_of_days' in journey_vals:
                    days = journey_vals['number_of_days']
                    if pickup and days > 0:
                        journey_vals['expected_return_datetime'] = pickup + timedelta(days=days)
                elif journey_vals.get('expected_return_datetime'):
                    expected = fields.Datetime.to_datetime(journey_vals['expected_return_datetime'])
                    if pickup and expected > pickup:
                        journey_vals['number_of_days'] = ceil((expected - pickup).total_seconds() / 86400)
                elif 'pickup_datetime' in journey_vals and pickup and journey.number_of_days > 0:
                    journey_vals['expected_return_datetime'] = pickup + timedelta(days=journey.number_of_days)
                return_value = super(Journey, journey).write(journey_vals)
            return return_value
        return super().write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        normalized = []
        for values in vals_list:
            vals = dict(values)
            pickup = fields.Datetime.to_datetime(vals['pickup_datetime']) if vals.get('pickup_datetime') else False
            if pickup and 'number_of_days' in vals and vals['number_of_days'] > 0:
                vals['expected_return_datetime'] = pickup + timedelta(days=vals['number_of_days'])
            elif pickup and vals.get('expected_return_datetime'):
                expected = fields.Datetime.to_datetime(vals['expected_return_datetime'])
                if expected > pickup:
                    vals['number_of_days'] = ceil((expected - pickup).total_seconds() / 86400)
            elif pickup and vals.get('number_of_days', 1) > 0:
                vals['expected_return_datetime'] = pickup + timedelta(days=vals.get('number_of_days', 1))
            normalized.append(vals)
        return super().create(normalized)

    @api.onchange('pickup_datetime', 'number_of_days')
    def _onchange_booking_duration(self):
        if self.pickup_datetime and self.number_of_days > 0:
            self.expected_return_datetime = self.pickup_datetime + timedelta(days=self.number_of_days)
        else:
            self.expected_return_datetime = False

    def action_continue(self):
        self.ensure_one()
        self.env.cr.execute('SELECT id FROM car_rental_journey WHERE id = %s FOR UPDATE', [self.id])
        self.invalidate_recordset()
        self._compute_progress()
        if self.step == 'customer':
            if not self.partner_id:
                raise ValidationError('Select a customer first.')
            self.details_started = True
        elif self.step == 'details':
            if not all([self.partner_id, self.destination_id, self.category_id, self.pickup_datetime]) or self.number_of_days < 1:
                raise ValidationError('Complete customer, destination, category, pickup time and a positive rental duration.')
            expected_return = self.pickup_datetime + timedelta(days=self.number_of_days)
            self.partner_id._check_rental_eligibility(self.pickup_datetime, expected_return)
            reservation = self.env['car.rental.reservation'].create({
                'company_id': self.company_id.id, 'partner_id': self.partner_id.id,
                'destination_id': self.destination_id.id, 'category_id': self.category_id.id,
                'vehicle_id': self.vehicle_id.id, 'pickup_datetime': self.pickup_datetime,
                'number_of_days': self.number_of_days})
            if not reservation.pricing_rule_id or reservation.quoted_daily_rate <= 0:
                raise ValidationError('Approve a matching pricing rule before continuing.')
            if not reservation.vehicle_id:
                reservation.action_allocate()
            super().write({'reservation_id': reservation.id, 'vehicle_id': reservation.vehicle_id.id,
                           'expected_return_datetime': reservation.expected_return_datetime,
                           'number_of_days': reservation.number_of_days})
        elif self.step == 'quote':
            self.reservation_id.action_confirm()
        elif self.step == 'confirm':
            self.reservation_id.action_create_rental()
        elif self.step == 'agreement':
            return self.action_agreement()
        elif self.step == 'payment':
            raise ValidationError('\n'.join(self.rental_id._journey_payment_blockers()))
        elif self.step == 'pickup':
            raise ValidationError('Complete the pickup inspection before handover.')
        elif self.step == 'handover':
            self.rental_id.action_start_rental()
        elif self.step == 'return':
            self.rental_id.action_return_vehicle()
        elif self.step == 'settlement':
            self.rental_id.action_close_journey()
        return self.action_open()

    def action_open(self):
        self.ensure_one()
        return window('Create a Booking', self._name, res_id=self.id)

    def action_cancel(self):
        self.ensure_one()
        self.check_access('write')
        self.env.cr.execute('SELECT id FROM car_rental_journey WHERE id=%s FOR UPDATE', [self.id])
        self.invalidate_recordset()
        if self.reservation_id:
            self.reservation_id.action_cancel()
        super().write({'cancelled': True})
        self.message_post(body='Booking cancelled. Existing records are retained for reference.')
        return self.action_open()

    def action_end_early(self):
        self.ensure_one()
        if self.rental_id.status != 'ongoing':
            raise ValidationError('Only a vehicle currently on hire can be returned early.')
        return self.action_inspection()

    def unlink(self):
        if any(self.mapped('reservation_id')):
            raise ValidationError('This booking has a reservation. Use Cancel Booking to retain its history.')
        return super().unlink()

    def action_save_exit(self):
        return self.env['ir.actions.actions']._for_xml_id('car_rental_management_odoo.action_booking_journeys')

    def action_back(self):
        self.ensure_one()
        if not self.reservation_id:
            self.details_started = False
            return self.action_open()
        return self.action_reservation()

    def action_customer(self):
        self.ensure_one()
        return window('Customer', 'res.partner', res_id=self.partner_id.id)

    def action_reservation(self):
        self.ensure_one()
        return window('Reservation', 'car.rental.reservation', res_id=self.reservation_id.id)

    def action_rental(self):
        self.ensure_one()
        return window('Rental', 'car.rental.rental', res_id=self.reservation_id.rental_ids[:1].id)

    def action_vehicle(self):
        self.ensure_one()
        return window('Fleet Follow-up', 'fleet.vehicle', res_id=(self.reservation_id.vehicle_id or self.vehicle_id).id)

    def action_invoice(self):
        return self.rental_id.action_invoice()

    def action_agreement(self):
        self.ensure_one()
        rental = self.rental_id
        if not rental:
            raise ValidationError('Confirm the booking and create its rental first.')
        if rental.contract_ids or rental.company_id.sudo().cr_contract_pdf:
            return rental.action_digital_contract()
        return self.action_rental()

    def action_payment(self):
        return self.rental_id.action_record_payment()

    def action_deposit(self):
        return self.rental_id.action_collect_deposit()

    def action_inspection(self):
        rental = self.rental_id
        kind = 'pickup' if rental.status == 'draft' else 'return'
        existing = rental.inspection_ids.filtered(lambda c: c.kind == kind)[:1]
        if existing:
            return window('Inspection', 'car.rental.check', res_id=existing.id)
        return rental.action_pickup_inspection() if kind == 'pickup' else rental.action_return_inspection()


class Rental(models.Model):
    _inherit = 'car.rental.rental'
    status = fields.Selection(selection_add=[('closed', 'Closed')], ondelete={'closed': 'set default'})
    closed_on = fields.Datetime(readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        if any(vals.get('closed_on') for vals in vals_list):
            raise ValidationError('Use Close Rental to record completion.')
        return super().create(vals_list)

    def _journey_payment_blockers(self):
        self.ensure_one()
        problems = []
        if not self.sale_order_id and not self.company_id.rental_allow_direct_invoice:
            problems.append('Create the rental sales quotation before invoicing.')
        if not self.sudo().invoice_ids.filtered(lambda m: m.rental_invoice_kind == 'rental' and m.state == 'posted' and m.move_type == 'out_invoice'):
            problems.append('Post the rental invoice.')
        if self.company_id.rental_require_full_payment and not self.currency_id.is_zero(self.balance_due):
            problems.append('Settle the rental payment required before pickup.')
        if self.currency_id.compare_amounts(self.deposit_held, self.deposit_required) < 0:
            problems.append('Collect the full required security deposit.')
        return problems

    def _journey_close_blockers(self):
        self.ensure_one()
        problems = []
        invoices = self.sudo().invoice_ids.filtered(lambda m: m.state != 'cancel')
        if self.status != 'returned' or not self.return_inspection_done:
            problems.append('Complete the vehicle return inspection and return action.')
        for kind, amount in [('rental', self.amount), ('late', self.late_charge), ('cleaning', self.cleaning_charge)]:
            if amount and not invoices.filtered(lambda m: m.rental_invoice_kind == kind and m.state == 'posted' and m.move_type == 'out_invoice'):
                problems.append('Create and post the %s invoice.' % kind)
        if invoices.filtered(lambda m: m.state == 'draft'):
            problems.append('Post or cancel draft invoices and credit notes.')
        if invoices.filtered(lambda m: m.state == 'posted' and not m.currency_id.is_zero(m.amount_residual)) or not self.currency_id.is_zero(self.balance_due):
            problems.append('Settle all outstanding invoices and credits.')
        if not self.currency_id.is_zero(self.deposit_held):
            problems.append('Apply approved charges to the deposit and refund the remaining deposit.')
        if self.damage_ids.filtered(lambda d: d.state == 'draft' or (d.cost > 0 and (d.invoice_id.state != 'posted' or not d.invoice_id.currency_id.is_zero(d.invoice_id.amount_residual)))):
            problems.append('Finish damage assessment and settle approved damage charges.')
        if self.deposit_transaction_ids.filtered(lambda d: d.state == 'draft') or self.payment_ids.filtered(lambda p: p.state == 'draft' and not p.rental_legacy):
            problems.append('Finish or remove unposted deposit transactions and payments.')
        return problems

    def action_close_journey(self):
        require_role(self.env, 'group_rental_accountant')
        for rental in self:
            self.env.cr.execute('SELECT id FROM car_rental_rental WHERE id = %s FOR UPDATE', [rental.id])
            rental.invalidate_recordset()
            problems = rental._journey_close_blockers()
            if problems:
                raise ValidationError('\n'.join(problems))
            from .operations import Rental as OperationalRental
            super(OperationalRental, rental).write({'status': 'closed', 'closed_on': fields.Datetime.now()})
            rental.message_post(body='Rental cycle closed after return and financial settlement.')

    def write(self, vals):
        if 'closed_on' in vals:
            raise ValidationError('Use Close Rental to record completion.')
        return super().write(vals)

    def action_booking_journey(self):
        self.ensure_one()
        return self.reservation_id.action_booking_journey()


class Reservation(models.Model):
    _inherit = 'car.rental.reservation'

    def write(self, vals):
        result = super().write(vals)
        keys = {'partner_id', 'destination_id', 'category_id', 'vehicle_id', 'pickup_datetime', 'expected_return_datetime', 'number_of_days'}
        if keys.intersection(vals):
            for reservation in self:
                journeys = self.env['car.rental.journey'].search([('reservation_id', '=', reservation.id)])
                values = {key: reservation[key].id if reservation._fields[key].type == 'many2one' else reservation[key] for key in keys}
                super(Journey, journeys).write(values)
        return result

    def action_booking_journey(self):
        self.ensure_one()
        self.env.cr.execute('SELECT id FROM car_rental_reservation WHERE id = %s FOR UPDATE', [self.id])
        journey = self.env['car.rental.journey'].search([('reservation_id', '=', self.id)], limit=1)
        if not journey:
            journey = self.env['car.rental.journey'].create({
                'company_id': self.company_id.id, 'reservation_id': self.id,
                'partner_id': self.partner_id.id, 'destination_id': self.destination_id.id,
                'category_id': self.category_id.id, 'vehicle_id': self.vehicle_id.id,
                'pickup_datetime': self.pickup_datetime, 'expected_return_datetime': self.expected_return_datetime,
                'number_of_days': self.number_of_days})
        elif journey.number_of_days != self.number_of_days:
            super(Journey, journey).write({'number_of_days': self.number_of_days})
        return journey.action_open()
