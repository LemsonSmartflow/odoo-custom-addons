"""A resumable booking workspace. Operational records remain authoritative."""
from odoo import api, fields, models
from odoo.exceptions import ValidationError
from .workflow import window
from .pricing import require_role


class Journey(models.Model):
    _name = 'car.rental.journey'
    _description = 'Booking Journey'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'
    _check_company_auto = True
    _reservation_unique = models.Constraint('UNIQUE(reservation_id)', 'This reservation already has a booking journey.')

    name = fields.Char(compute='_compute_progress')
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    customer_id = fields.Many2one('car.rental.customer', check_company=True)
    destination_id = fields.Many2one('car.rental.zone', check_company=True)
    category_id = fields.Many2one('car.rental.category', check_company=True)
    vehicle_id = fields.Many2one('car.rental.vehicle', check_company=True)
    pickup_datetime = fields.Datetime()
    expected_return_datetime = fields.Datetime(string='Return Date and Time')
    reservation_id = fields.Many2one('car.rental.reservation', readonly=True, copy=False, check_company=True)
    rental_id = fields.Many2one('car.rental.rental', compute='_compute_progress')
    details_started = fields.Boolean(copy=False)
    currency_id = fields.Many2one(related='company_id.currency_id')
    amount = fields.Float(related='reservation_id.amount')
    deposit_required = fields.Monetary(related='reservation_id.deposit_required')
    cleaning_fee = fields.Monetary(related='reservation_id.cleaning_fee')
    number_of_days = fields.Integer(related='reservation_id.number_of_days')
    vehicle_image = fields.Image(related='vehicle_id.image_1920')
    guidance = fields.Text(compute='_compute_progress')
    step = fields.Selection([(s, label) for s, label in [
        ('customer', '1 Customer'), ('details', '2 Booking'), ('quote', '3 Quote'),
        ('confirm', '4 Confirm'), ('agreement', '5 Agreement'), ('payment', '6 Payment'), ('pickup', '7 Pickup Inspection'),
        ('handover', '8 Handover'), ('return', '9 Return'), ('settlement', '10 Settlement'),
        ('closed', '11 Closed'), ('cancelled', 'Cancelled')]], compute='_compute_progress')

    @api.depends('customer_id', 'details_started', 'reservation_id.status', 'reservation_id.reference',
                 'reservation_id.rental_ids.status', 'reservation_id.rental_ids.agreement_state',
                 'reservation_id.rental_ids.inspection_ids.state', 'reservation_id.rental_ids.deposit_held',
                 'reservation_id.rental_ids.balance_due', 'reservation_id.rental_ids.invoice_ids.state',
                 'reservation_id.rental_ids.invoice_ids.amount_residual')
    def _compute_progress(self):
        for journey in self:
            reservation = journey.reservation_id
            rental = reservation.rental_ids[:1]
            journey.rental_id = rental
            journey.name = reservation.reference or ('Booking: %s' % journey.customer_id.display_name if journey.customer_id else 'New Booking')
            step, guidance = 'customer', 'Select or create the customer. Complete identity, licence and address details.'
            if journey.details_started:
                step, guidance = 'details', 'Choose destination, category, pickup and return times. Continue to calculate the quote.'
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
            if reservation.status == 'cancelled':
                step, guidance = 'cancelled', 'This reservation was cancelled. Start a new journey for a new booking.'
            journey.step, journey.guidance = step, guidance

    def write(self, vals):
        if 'reservation_id' in vals:
            raise ValidationError('Use Continue to link the reservation.')
        if {'customer_id', 'company_id', 'destination_id', 'category_id', 'vehicle_id', 'pickup_datetime', 'expected_return_datetime'}.intersection(vals) and any(self.mapped('reservation_id')):
            raise ValidationError('Edit the linked reservation to change booking details.')
        return super().write(vals)

    def action_continue(self):
        self.ensure_one()
        self.env.cr.execute('SELECT id FROM car_rental_journey WHERE id = %s FOR UPDATE', [self.id])
        self.invalidate_recordset()
        self._compute_progress()
        if self.step == 'customer':
            if not self.customer_id:
                raise ValidationError('Select a customer first.')
            self.details_started = True
        elif self.step == 'details':
            if not all([self.customer_id, self.destination_id, self.category_id, self.pickup_datetime, self.expected_return_datetime]):
                raise ValidationError('Complete customer, destination, category, pickup and return times.')
            self.customer_id._check_rental_eligibility(self.pickup_datetime, self.expected_return_datetime)
            reservation = self.env['car.rental.reservation'].create({
                'company_id': self.company_id.id, 'customer_id': self.customer_id.id,
                'destination_id': self.destination_id.id, 'category_id': self.category_id.id,
                'vehicle_id': self.vehicle_id.id, 'pickup_datetime': self.pickup_datetime,
                'expected_return_datetime': self.expected_return_datetime})
            if not reservation.pricing_rule_id or reservation.quoted_daily_rate <= 0:
                raise ValidationError('Approve a matching pricing rule before continuing.')
            if not reservation.vehicle_id:
                reservation.action_allocate()
            super().write({'reservation_id': reservation.id, 'vehicle_id': reservation.vehicle_id.id})
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
        return window('Booking Journey', self._name, res_id=self.id)

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
        return window('Customer', 'car.rental.customer', res_id=self.customer_id.id)

    def action_reservation(self):
        self.ensure_one()
        return window('Reservation', 'car.rental.reservation', res_id=self.reservation_id.id)

    def action_rental(self):
        self.ensure_one()
        return window('Rental', 'car.rental.rental', res_id=self.reservation_id.rental_ids[:1].id)

    def action_vehicle(self):
        self.ensure_one()
        return window('Fleet Follow-up', 'car.rental.vehicle', res_id=(self.reservation_id.vehicle_id or self.vehicle_id).id)

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
        if self.deposit_transaction_ids.filtered(lambda d: d.state == 'draft') or self.payment_ids.filtered(lambda p: p.ledger_state == 'draft'):
            problems.append('Finish or remove unposted deposit transactions and receipts.')
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
        keys = {'customer_id', 'destination_id', 'category_id', 'vehicle_id', 'pickup_datetime', 'expected_return_datetime'}
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
                'customer_id': self.customer_id.id, 'destination_id': self.destination_id.id,
                'category_id': self.category_id.id, 'vehicle_id': self.vehicle_id.id,
                'pickup_datetime': self.pickup_datetime, 'expected_return_datetime': self.expected_return_datetime})
        return journey.action_open()
