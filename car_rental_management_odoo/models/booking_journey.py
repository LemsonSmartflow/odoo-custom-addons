"""A resumable booking controller. Reservations and rentals remain authoritative."""
from datetime import timedelta
from math import ceil

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from .pricing import require_role
from .workflow import window


JOURNEY_STEPS = [
    ('booking', '1 Booking'),
    ('quote', '2 Quote'),
    ('agreement', '3 Agreement'),
    ('payment', '4 Payment'),
    ('pickup', '5 Pickup'),
    ('on_hire', '6 On Hire'),
    ('return', '7 Return'),
    ('settlement', '8 Settlement'),
    ('closed', 'Closed'),
    ('cancelled', 'Cancelled'),
]


class Journey(models.Model):
    _name = 'car.rental.journey'
    _description = 'Booking'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'
    _check_company_auto = True
    _reservation_unique = models.Constraint(
        'UNIQUE(reservation_id)', 'This reservation already has a booking.')

    name = fields.Char(compute='_compute_name')
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    reservation_id = fields.Many2one(
        'car.rental.reservation', readonly=True, copy=False, check_company=True)
    rental_id = fields.Many2one('car.rental.rental', compute='_compute_rental')
    sales_order_id = fields.Many2one('sale.order', compute='_compute_sales_order')
    sales_order_state = fields.Char(compute='_compute_sales_order')
    pickup_inspection_done = fields.Boolean(compute='_compute_pickup_inspection_done')
    rental_status = fields.Selection(
        [('draft', 'Draft'), ('ongoing', 'Ongoing'), ('returned', 'Returned'),
         ('closed', 'Closed'), ('cancelled', 'Cancelled')],
        compute='_compute_rental_progress')
    agreement_signed = fields.Boolean(compute='_compute_rental_progress')
    payment_ready = fields.Boolean(compute='_compute_rental_progress')
    step = fields.Selection(JOURNEY_STEPS, required=True, default='booking', copy=False, index=True)
    guidance = fields.Text(compute='_compute_guidance')
    cancelled = fields.Boolean(readonly=True, copy=False)

    # These are only used to collect the required details before the draft
    # reservation can be created. All post-booking fields below write through.
    booking_partner_id = fields.Many2one('res.partner', string='Customer', check_company=True)
    booking_destination_id = fields.Many2one('car.rental.zone', string='Destination', check_company=True)
    booking_category_id = fields.Many2one('fleet.vehicle.model.category', string='Vehicle Category')
    booking_vehicle_id = fields.Many2one('fleet.vehicle', string='Vehicle', check_company=True)
    booking_pickup_datetime = fields.Datetime(string='Pickup Date and Time')
    booking_number_of_days = fields.Integer(string='Rental Days (24-hour periods)', default=1)
    booking_return_datetime = fields.Datetime(
        compute='_compute_booking_return_datetime', string='Return Date and Time')
    booking_delivery_service = fields.Boolean(string='Deliver the vehicle to the customer')
    booking_delivery_address = fields.Char(string='Delivery Address')
    booking_delivery_fee = fields.Monetary(
        string='Delivery Charge', currency_field='currency_id')
    booking_collection_service = fields.Boolean(
        string='Collect the vehicle from another location')
    booking_collection_address = fields.Char(string='Collection Address')
    booking_collection_fee = fields.Monetary(
        string='Off-site Collection Charge', currency_field='currency_id', readonly=True)
    reservation_status = fields.Selection(related='reservation_id.status')
    agreement_delivery_place = fields.Char(string='Agreement Delivery Place')
    agreement_payment_advance_days = fields.Integer(
        string='Payment Advance Deadline (days)', default=0)
    agreement_company_email = fields.Char(
        string='Company Notices Email',
        default=lambda self: self.env.company.email or self.env.company.partner_id.email)
    agreement_company_representative = fields.Char(string='Company Representative')
    agreement_company_witness_1 = fields.Char(string='Company Witness 1')
    agreement_company_witness_2 = fields.Char(string='Company Witness 2')
    agreement_renter_witness_1 = fields.Char(string='Renter Witness 1')
    agreement_renter_witness_2 = fields.Char(string='Renter Witness 2')
    agreement_customer_email = fields.Char(
        related='partner_id.email', string='Customer Email')
    agreement_signature_count = fields.Integer(compute='_compute_agreement_progress')
    agreement_signing_url = fields.Char(compute='_compute_agreement_signing_url')
    agreement_contract_state = fields.Selection(
        [('draft', 'Not Sent'), ('sent', 'Awaiting Customer'),
         ('signing', 'Awaiting Other Signatures'), ('complete', 'Signed'),
         ('cancelled', 'Revoked'), ('expired', 'Expired')],
        compute='_compute_agreement_progress', string='Agreement Status')

    partner_id = fields.Many2one(
        related='reservation_id.partner_id', string='Customer', readonly=False)
    destination_id = fields.Many2one(
        related='reservation_id.destination_id', string='Destination', readonly=False)
    category_id = fields.Many2one(
        related='reservation_id.category_id', string='Vehicle Category', readonly=False)
    vehicle_id = fields.Many2one(
        related='reservation_id.vehicle_id', string='Vehicle', readonly=False)
    pickup_datetime = fields.Datetime(
        related='reservation_id.pickup_datetime', string='Pickup Date and Time', readonly=False)
    expected_return_datetime = fields.Datetime(
        related='reservation_id.expected_return_datetime', string='Return Date and Time', readonly=False)
    number_of_days = fields.Integer(
        related='reservation_id.number_of_days', string='Rental Days (24-hour periods)', readonly=False)

    currency_id = fields.Many2one(related='company_id.currency_id')
    amount = fields.Monetary(related='reservation_id.amount', string='Hire Total')
    deposit_required = fields.Monetary(related='reservation_id.deposit_required')
    cleaning_fee = fields.Monetary(related='reservation_id.cleaning_fee')
    quote_service_total = fields.Monetary(related='reservation_id.quote_service_total')
    quote_total = fields.Monetary(related='reservation_id.quote_total')
    delivery_service = fields.Boolean(related='reservation_id.delivery_service')
    delivery_address = fields.Char(related='reservation_id.delivery_address')
    delivery_fee = fields.Monetary(related='reservation_id.delivery_fee')
    return_collection_service = fields.Boolean(
        compute='_compute_return_collection', inverse='_inverse_return_collection')
    return_collection_address = fields.Char(compute='_compute_return_collection')
    return_collection_fee = fields.Monetary(
        compute='_compute_return_collection', currency_field='currency_id')
    return_charges_confirmed = fields.Boolean(compute='_compute_return_collection')
    customer_deposit_credit = fields.Monetary(
        compute='_compute_customer_deposit_credit', string='Prior Deposit Credit Available')
    vehicle_image = fields.Image(related='vehicle_id.rental_image')

    @api.depends('booking_pickup_datetime', 'booking_number_of_days')
    def _compute_booking_return_datetime(self):
        for journey in self:
            journey.booking_return_datetime = (
                journey.booking_pickup_datetime + timedelta(days=journey.booking_number_of_days)
                if journey.booking_pickup_datetime and journey.booking_number_of_days > 0 else False)

    @api.onchange('booking_destination_id', 'destination_id')
    def _onchange_agreement_delivery_place(self):
        for journey in self:
            destination = journey.destination_id or journey.booking_destination_id
            if destination and not journey.agreement_delivery_place:
                journey.agreement_delivery_place = destination.name

    @api.onchange('company_id')
    def _onchange_agreement_company_email(self):
        for journey in self:
            if not journey.agreement_company_email and journey.company_id:
                journey.agreement_company_email = (
                    journey.company_id.email or journey.company_id.partner_id.email)

    @api.onchange('booking_delivery_service')
    def _onchange_booking_delivery_service(self):
        for journey in self:
            if journey.booking_delivery_service and not journey.booking_delivery_fee:
                product = journey.company_id.cr_delivery_product_id
                if product:
                    journey.booking_delivery_fee = product.list_price
            elif not journey.booking_delivery_service:
                journey.booking_delivery_address = False
                journey.booking_delivery_fee = 0

    @api.depends('reservation_id.reference', 'booking_partner_id.name')
    def _compute_name(self):
        for journey in self:
            journey.name = journey.reservation_id.reference or (
                'Booking: %s' % journey.booking_partner_id.display_name
                if journey.booking_partner_id else 'New Booking')

    @api.depends(
        'reservation_id.rental_ids.return_collection_service',
        'reservation_id.rental_ids.return_collection_address',
        'reservation_id.rental_ids.return_collection_fee',
        'reservation_id.rental_ids.return_charges_confirmed')
    def _compute_return_collection(self):
        for journey in self:
            rental = journey.reservation_id.rental_ids[:1]
            journey.return_collection_service = rental.return_collection_service if rental else False
            journey.return_collection_address = rental.return_collection_address if rental else False
            journey.return_collection_fee = rental.return_collection_fee if rental else 0
            journey.return_charges_confirmed = rental.return_charges_confirmed if rental else False

    def _inverse_return_collection(self):
        for journey in self:
            rental = journey.reservation_id.rental_ids[:1]
            if not rental or journey.step != 'return' or rental.status != 'ongoing':
                raise ValidationError(
                    'Vehicle collection can only be changed during the Return step before the vehicle is returned.')
            rental.write({'return_collection_service': journey.return_collection_service})

    @api.depends('reservation_id.rental_ids')
    def _compute_rental(self):
        for journey in self:
            journey.rental_id = journey.reservation_id.rental_ids[:1]

    @api.depends('reservation_id.rental_ids.sale_order_id',
                 'reservation_id.rental_ids.sale_order_id.state')
    def _compute_sales_order(self):
        for journey in self:
            order = journey.reservation_id.rental_ids.sale_order_id[:1]
            journey.sales_order_id = order
            journey.sales_order_state = order.state if order else False

    @api.depends(
        'reservation_id.rental_ids.status',
        'reservation_id.rental_ids.agreement_state',
        'reservation_id.rental_ids.payment_status',
        'reservation_id.rental_ids.balance_due',
        'reservation_id.rental_ids.deposit_required',
        'reservation_id.rental_ids.deposit_held',
        'reservation_id.rental_ids.invoice_ids.state',
        'reservation_id.rental_ids.invoice_ids.amount_residual',
        'company_id.rental_require_full_payment')
    def _compute_rental_progress(self):
        for journey in self:
            rental = journey.reservation_id.rental_ids[:1]
            journey.rental_status = rental.status if rental else False
            journey.agreement_signed = bool(
                rental and rental.agreement_state == 'signed')
            journey.payment_ready = bool(
                rental and journey.agreement_signed
                and not rental._journey_payment_blockers())

    @api.depends('reservation_id.rental_ids.contract_ids.state',
                 'reservation_id.rental_ids.contract_ids.expires_on',
                 'reservation_id.rental_ids.contract_ids.signer_ids.signed_on')
    def _compute_agreement_progress(self):
        for journey in self:
            contract = journey.reservation_id.rental_ids.contract_ids.filtered(
                lambda item: item.state != 'cancelled')[:1]
            journey.agreement_contract_state = (
                'expired' if contract and contract.state in ('sent', 'signing')
                and (not contract.expires_on or contract.expires_on <= fields.Datetime.now())
                else contract.state if contract else 'draft')
            journey.agreement_signature_count = len(
                contract.signer_ids.filtered('signed_on')) if contract else 0

    @api.depends(
        'reservation_id.rental_ids.contract_ids.state',
        'reservation_id.rental_ids.contract_ids.expires_on',
        'reservation_id.rental_ids.contract_ids.signer_ids.role',
        'reservation_id.rental_ids.contract_ids.signer_ids.token')
    def _compute_agreement_signing_url(self):
        for journey in self:
            contract = journey.reservation_id.rental_ids.contract_ids.filtered(
                lambda item: item.state in ('sent', 'signing')
                and item.expires_on and item.expires_on > fields.Datetime.now())[:1]
            renter = contract.signer_ids.filtered(lambda signer: signer.role == 'renter')
            journey.agreement_signing_url = renter.link if len(renter) == 1 else False

    @api.depends('reservation_id.rental_ids.pickup_inspection_done')
    def _compute_pickup_inspection_done(self):
        for journey in self:
            journey.pickup_inspection_done = bool(
                journey.reservation_id.rental_ids[:1].pickup_inspection_done)

    @api.depends('booking_partner_id', 'company_id')
    def _compute_customer_deposit_credit(self):
        Rentals = self.env['car.rental.rental']
        for journey in self:
            partner = journey.partner_id or journey.booking_partner_id
            sources = Rentals._deposit_credit_sources(partner, journey.company_id)
            journey.customer_deposit_credit = sum(sources.mapped('deposit_held'))

    @api.depends('step', 'reservation_id.rental_ids.damage_ids.state')
    def _compute_guidance(self):
        guidance = {
            'booking': 'Enter the customer, destination, category, pickup time and rental duration. Select a vehicle or leave it empty for automatic allocation. If delivery is needed, enter its address and charge here.',
            'quote': 'This booking and the Sales app use one quotation record. Send or confirm it here; Sales users can open the same record in Sales when needed.',
            'agreement': 'The booking and customer details fill the agreement automatically. Complete any missing signer names, then send the customer their private signing link.',
            'payment': 'An accountant records payment and applies any eligible prior deposit credit. The booking advances when the payment policy is met.',
            'pickup': 'Complete the pickup inspection. Continue again to hand over the vehicle after the inspection is complete.',
            'on_hire': 'The vehicle has been handed over and the rental is active. Save and exit this booking; begin the return process when the customer brings the vehicle back.',
            'return': 'Complete the return inspection. Select vehicle collection from another location if needed, then confirm any late, cleaning or collection charge before returning the vehicle.',
            'settlement': 'Resolve draft damage assessments, post one final invoice for approved charges, settle it and refund any remaining deposit.',
            'closed': 'Booking cycle complete. Fleet cleaning and release remain available from the vehicle record.',
            'cancelled': 'This booking was cancelled. Existing operational and financial records are retained for reference.',
        }
        for journey in self:
            if (
                journey.step == 'settlement'
                and journey.rental_id.damage_ids.filtered(lambda damage: damage.state == 'draft')
            ):
                journey.guidance = 'Manager approval of damage required before settlement.'
            else:
                journey.guidance = guidance[journey.step]

    def write(self, vals):
        if {'step', 'cancelled', 'reservation_id'}.intersection(vals):
            raise ValidationError('Use the booking workflow actions to change the journey stage or linked records.')
        return super().write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'step' in vals and vals['step'] != 'booking':
                raise ValidationError('New bookings always start at the Booking step.')
            if 'default_partner_id' in self.env.context and not vals.get('booking_partner_id'):
                vals['booking_partner_id'] = self.env.context['default_partner_id']
            if 'default_vehicle_id' in self.env.context and not vals.get('booking_vehicle_id'):
                vals['booking_vehicle_id'] = self.env.context['default_vehicle_id']
        return super().create(vals_list)

    def _advance_to(self, step):
        self.ensure_one()
        allowed = {
            'booking': 'quote',
            'quote': 'agreement',
            'agreement': 'payment',
            'payment': 'pickup',
            'pickup': 'on_hire',
            'on_hire': 'return',
            'return': 'settlement',
            'settlement': 'closed',
        }
        self.env.cr.execute('SELECT id FROM car_rental_journey WHERE id = %s FOR UPDATE', [self.id])
        self.invalidate_recordset(['step'])
        if self.step == step:
            return
        if step != 'cancelled' and allowed.get(self.step) != step:
            raise ValidationError('This booking cannot move from %s to %s.' % (self.step, step))
        super(Journey, self).write({'step': step, 'cancelled': step == 'cancelled'})

    def _booking_values(self):
        self.ensure_one()
        if self.reservation_id:
            reservation = self.reservation_id
            if not all((reservation.partner_id, reservation.destination_id,
                        reservation.category_id, reservation.pickup_datetime)):
                raise ValidationError('Select a customer, destination, vehicle category and pickup time.')
            reservation.partner_id.sudo()._check_rental_eligibility(
                reservation.pickup_datetime, reservation.expected_return_datetime)
            return {
                'company_id': self.company_id.id,
                'partner_id': reservation.partner_id.id,
                'destination_id': reservation.destination_id.id,
                'category_id': reservation.category_id.id,
                'vehicle_id': reservation.vehicle_id.id,
                'pickup_datetime': reservation.pickup_datetime,
                'expected_return_datetime': reservation.expected_return_datetime,
                'start_date': reservation.start_date,
                'end_date': reservation.end_date,
                'number_of_days': reservation.number_of_days,
            }
        if not all((self.booking_partner_id, self.booking_destination_id,
                    self.booking_category_id, self.booking_pickup_datetime)):
            raise ValidationError('Select a customer, destination, vehicle category and pickup time.')
        if self.booking_number_of_days < 1:
            raise ValidationError('Rental duration must be at least one 24-hour day.')
        expected = self.booking_pickup_datetime + timedelta(days=self.booking_number_of_days)
        self.booking_partner_id.sudo()._check_rental_eligibility(
            self.booking_pickup_datetime, expected)
        return {
            'company_id': self.company_id.id,
            'partner_id': self.booking_partner_id.id,
            'destination_id': self.booking_destination_id.id,
            'category_id': self.booking_category_id.id,
            'vehicle_id': self.booking_vehicle_id.id,
            'pickup_datetime': self.booking_pickup_datetime,
            'expected_return_datetime': expected,
            'start_date': self.booking_pickup_datetime.date(),
            'end_date': expected.date(),
            'number_of_days': self.booking_number_of_days,
        }

    def _ensure_draft_reservation(self):
        self.ensure_one()
        vals = self._booking_values()
        if self.booking_delivery_service:
            if not self.company_id.cr_delivery_product_id:
                raise ValidationError('Configure the customer delivery service product in Car Rental Settings.')
            if not self.booking_delivery_address or self.booking_delivery_fee <= 0:
                raise ValidationError('Customer delivery requires an address and a positive charge.')
        reservation = self.reservation_id
        if reservation:
            if reservation.status != 'draft':
                raise ValidationError('This reservation is already confirmed; its booking details are locked.')
        else:
            reservation = self.env['car.rental.reservation'].create(vals)
            super(Journey, self).write({'reservation_id': reservation.id})
        reservation.write(self._booking_service_values())
        if not reservation.pricing_rule_id or reservation.quoted_daily_rate <= 0:
            raise ValidationError('Approve a matching pricing rule before continuing.')
        if not reservation.vehicle_id:
            reservation.action_allocate()
        return reservation

    def _prepare_quote(self):
        self.ensure_one()
        if self.step != 'booking':
            raise ValidationError('The sales quotation can only be prepared from the Booking step.')
        self._ensure_draft_reservation()
        return self._ensure_sales_quotation()

    def _ensure_sales_quotation(self):
        self.ensure_one()
        reservation = self.reservation_id
        if not reservation:
            raise ValidationError('Complete the booking details before preparing its quotation.')
        if reservation.status == 'draft':
            reservation.action_confirm()
        rental = reservation.rental_ids[:1]
        if not rental:
            reservation.sudo().action_create_rental()
            rental = reservation.rental_ids[:1]
        if (not self.agreement_delivery_place
                or self.agreement_delivery_place == reservation.destination_id.name):
            self.agreement_delivery_place = (
                reservation.delivery_address if reservation.delivery_service
                else reservation.destination_id.name)
        if not self.agreement_company_email:
            self.agreement_company_email = (
                self.company_id.email or self.company_id.partner_id.email)
        rental.sudo()._ensure_sale_order(include_deposit=True)
        return rental.sale_order_id

    def _booking_service_values(self):
        self.ensure_one()
        return {
            'delivery_service': self.booking_delivery_service,
            'delivery_address': self.booking_delivery_address if self.booking_delivery_service else False,
            'delivery_fee': self.booking_delivery_fee if self.booking_delivery_service else 0,
        }

    def action_quote_charges(self):
        self.ensure_one()
        if self.step != 'booking' or not self.booking_delivery_service:
            raise ValidationError('Select customer delivery in Booking first.')
        self._booking_values()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Customer Delivery',
            'res_model': 'car.rental.quote.charge.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_journey_id': self.id},
        }

    def _finish_quote(self):
        self.ensure_one()
        if self.step != 'quote' or not self.reservation_id:
            raise ValidationError('This booking is not ready to confirm its quote.')
        order = self._ensure_sales_quotation()
        if order.state in ('draft', 'sent'):
            order.sudo().action_confirm()
        if self.step == 'quote':
            self._advance_to('agreement')
        return self.action_open()

    def action_confirm_quotation(self):
        return self._finish_quote()

    def action_send_quotation(self):
        self.ensure_one()
        if self.step != 'quote':
            raise ValidationError('The Odoo quotation can only be sent from the Quote step.')
        order = self._ensure_sales_quotation()
        if order.state not in ('draft', 'sent'):
            raise ValidationError('Only a draft quotation can be sent.')
        return order.sudo().action_quotation_send()

    def action_open_quotation(self):
        self.ensure_one()
        if self.step != 'quote':
            raise ValidationError('The Odoo quotation can only be opened from the Quote step.')
        order = self._ensure_sales_quotation()
        return window('Sales Quotation', 'sale.order', res_id=order.id)

    def action_continue(self):
        self.ensure_one()
        self.env.cr.execute('SELECT id FROM car_rental_journey WHERE id = %s FOR UPDATE', [self.id])
        self.invalidate_recordset(['step', 'reservation_id'])
        if self.step == 'booking':
            if self.reservation_id and self.reservation_id.status != 'draft':
                self._advance_to('quote')
            else:
                self._prepare_quote()
                self._advance_to('quote')
        elif self.step == 'quote':
            return self._finish_quote()
        elif self.step == 'agreement':
            if self.rental_id.agreement_state == 'signed':
                self._advance_to('payment')
                return self.action_open()
            return self.action_agreement()
        elif self.step == 'payment':
            if not self.rental_id._journey_payment_blockers():
                self._advance_to('pickup')
                return self.action_open()
            return self.action_collect_payment()
        elif self.step == 'pickup':
            if self.rental_id.status == 'ongoing':
                self._advance_to('on_hire')
                return self.action_open()
            if not self.rental_id.pickup_inspection_done:
                return self.action_inspection()
            self.rental_id.action_start_rental()
            self._advance_to('on_hire')
        elif self.step == 'on_hire':
            return self.action_open()
        elif self.step == 'return':
            if self.rental_id.status == 'returned':
                self._advance_to('settlement')
                return self.action_open()
            if not self.rental_id.return_inspection_done:
                return self.action_inspection()
            if self.rental_id._uses_single_invoice() and not self.rental_id.return_charges_confirmed:
                details = self.rental_id._return_charge_details()
                if (
                    details['late_days'] or details['cleaning_required']
                    or self.rental_id.return_collection_service
                ):
                    return self.rental_id.action_return_charge_wizard()
            self.rental_id.action_return_vehicle()
            self._advance_to('settlement')
        elif self.step == 'settlement':
            return self.rental_id._prepare_settlement()
        else:
            raise ValidationError('This booking has already finished.')
        return self.action_open()

    def action_open(self):
        self.ensure_one()
        return window('Bookings', self._name, res_id=self.id)

    def action_cancel(self):
        self.ensure_one()
        self.check_access('write')
        if self.rental_id:
            self.rental_id._cancel_before_pickup()
        elif self.reservation_id:
            self.reservation_id.action_cancel()
        else:
            super(Journey, self).write({'cancelled': True})
        self._advance_to('cancelled')
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
        return self.env['ir.actions.actions']._for_xml_id(
            'car_rental_management_odoo.action_booking_journeys')

    def action_back(self):
        self.ensure_one()
        previous = {
            'quote': 'booking', 'agreement': 'quote', 'payment': 'agreement',
            'pickup': 'payment', 'return': 'on_hire', 'settlement': 'return',
        }.get(self.step)
        if not previous:
            return self.action_open()
        if previous == 'booking' and self.reservation_id:
            super(Journey, self).write({
                'booking_delivery_service': self.reservation_id.delivery_service,
                'booking_delivery_address': self.reservation_id.delivery_address,
                'booking_delivery_fee': self.reservation_id.delivery_fee,
            })
        super(Journey, self).write({'step': previous})
        return self.action_open()

    def action_customer(self):
        self.ensure_one()
        return window('Customer', 'res.partner', res_id=self.partner_id.id)

    def action_reservation(self):
        self.ensure_one()
        return window('Reservation', 'car.rental.reservation', res_id=self.reservation_id.id)

    def action_rental(self):
        self.ensure_one()
        return window('Rental', 'car.rental.rental', res_id=self.rental_id.id)

    def action_vehicle(self):
        self.ensure_one()
        vehicle = self.vehicle_id or self.booking_vehicle_id
        return window('Fleet Follow-up', 'fleet.vehicle', res_id=vehicle.id)

    def action_vehicle_preview(self):
        self.ensure_one()
        if not (self.category_id or self.booking_category_id):
            raise ValidationError('Select a vehicle category before choosing a vehicle.')
        vehicle = self.vehicle_id or self.booking_vehicle_id
        preview = self.env['car.rental.vehicle.preview'].create({
            'journey_id': self.id,
            'vehicle_id': vehicle.id if vehicle else False,
        })
        return preview._reopen()

    def action_agreement(self):
        self.ensure_one()
        if not self.rental_id:
            raise ValidationError('Confirm the quote before preparing the agreement.')
        if self.rental_id.contract_ids or self.rental_id.company_id.sudo().cr_contract_pdf:
            return self.rental_id.action_digital_contract()
        return self.action_rental()

    def action_collect_payment(self):
        self.ensure_one()
        require_role(self.env, 'group_rental_accountant')
        return self.rental_id.action_collect_payment()

    def action_handover(self):
        self.ensure_one()
        if self.step == 'pickup' and self.rental_id.status == 'ongoing':
            self._advance_to('on_hire')
            return self.action_open()
        if self.step != 'pickup' or not self.rental_id.pickup_inspection_done:
            raise ValidationError('Complete the pickup inspection before handing over the vehicle.')
        self.rental_id.action_start_rental()
        self._advance_to('on_hire')
        return self.action_open()

    def action_begin_return(self):
        self.ensure_one()
        if self.step != 'on_hire' or self.rental_id.status != 'ongoing':
            raise ValidationError('The return process can begin only after handover while the rental is active.')
        self._advance_to('return')
        return self.action_open()

    def action_close_rental(self):
        self.ensure_one()
        require_role(self.env, 'group_rental_accountant')
        self.rental_id.action_close_journey()
        return self.action_open()

    def action_inspection(self):
        self.ensure_one()
        rental = self.rental_id
        if self.step not in ('pickup', 'return'):
            raise ValidationError('Inspections can only be opened during Pickup or Return.')
        kind = 'pickup' if self.step == 'pickup' else 'return'
        inspection = rental.inspection_ids.filtered(
            lambda record: record.kind == kind and record.state != 'done')[:1]
        if inspection:
            return window('Inspection', 'car.rental.check', res_id=inspection.id)
        return rental.action_pickup_inspection() if kind == 'pickup' else rental.action_return_inspection()

    def action_approve_damage(self):
        self.ensure_one()
        require_role(self.env, 'group_rental_manager')
        damage = self.rental_id.damage_ids.filtered(lambda case: case.state == 'draft')[:1]
        if not damage:
            raise ValidationError('There are no draft damage cases to approve.')
        return window('Damage Assessment', 'car.rental.damage.case', res_id=damage.id)


class VehiclePreview(models.TransientModel):
    _name = 'car.rental.vehicle.preview'
    _description = 'Vehicle Photo Preview'

    journey_id = fields.Many2one('car.rental.journey', required=True, readonly=True)
    company_id = fields.Many2one(related='journey_id.company_id')
    category_id = fields.Many2one('fleet.vehicle.model.category', compute='_compute_category')
    available_vehicle_ids = fields.Many2many(
        'fleet.vehicle', compute='_compute_available_vehicles',
        string='Available Vehicles')
    vehicle_id = fields.Many2one(
        'fleet.vehicle', string='Vehicle',
        domain="[('id', 'in', available_vehicle_ids)]")
    option_ids = fields.One2many(
        'car.rental.vehicle.preview.option', 'preview_id',
        string='Vehicle Choices', readonly=True)
    image = fields.Image(related='vehicle_id.rental_image', readonly=True)
    image_1920 = fields.Image(related='vehicle_id.image_1920', readonly=True)
    name = fields.Char(related='vehicle_id.display_name', string='Vehicle Name')
    license_plate = fields.Char(related='vehicle_id.license_plate')
    rental_status = fields.Selection(related='vehicle_id.rental_status')

    @api.depends('journey_id.reservation_id', 'journey_id.category_id', 'journey_id.booking_category_id')
    def _compute_category(self):
        for preview in self:
            preview.category_id = (
                preview.journey_id.category_id or preview.journey_id.booking_category_id)

    @api.depends(
        'journey_id.reservation_id', 'journey_id.reservation_id.available_vehicle_ids',
        'journey_id.category_id', 'journey_id.booking_category_id',
        'journey_id.booking_pickup_datetime', 'journey_id.booking_number_of_days',
        'company_id')
    def _compute_available_vehicles(self):
        for preview in self:
            preview.available_vehicle_ids = preview._search_available_vehicles()

    def _search_available_vehicles(self):
        """Vehicles that can still be allocated for this booking's period."""
        self.ensure_one()
        Vehicle = self.env['fleet.vehicle']
        category = self.category_id
        if not category:
            return Vehicle
        reservation = self.journey_id.reservation_id
        if reservation:
            return reservation.available_vehicle_ids.sorted('license_plate')
        pickup = self.journey_id.booking_pickup_datetime
        return_datetime = self.journey_id.booking_return_datetime
        candidates = Vehicle.search([
            ('company_id', '=', self.company_id.id),
            ('rental_category_id', '=', category.id),
            ('rental_status', 'in', ['available', 'reserved', 'rented']),
            ('license_plate', '!=', False),
        ])
        if pickup and return_datetime:
            conflicts = self.env['car.rental.reservation'].search([
                ('vehicle_id', 'in', candidates.ids),
                ('status', '!=', 'cancelled'),
                ('pickup_datetime', '<', return_datetime),
                ('expected_return_datetime', '>', pickup),
            ])
            candidates -= conflicts.mapped('vehicle_id')
        return candidates.sorted('license_plate')

    @api.model_create_multi
    def create(self, vals_list):
        previews = super().create(vals_list)
        previews._refresh_options()
        return previews

    def _refresh_options(self):
        """Rebuild the scrolling choice list from the currently available fleet."""
        Option = self.env['car.rental.vehicle.preview.option']
        for preview in self:
            preview.option_ids.unlink()
            vehicles = preview.available_vehicle_ids
            if vehicles:
                Option.create([
                    {'preview_id': preview.id, 'vehicle_id': vehicle.id}
                    for vehicle in vehicles
                ])
        return True

    def _reopen(self):
        """Refresh this wizard in place after a car is picked from the list."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Choose a Vehicle',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_select_vehicle(self):
        self.ensure_one()
        if not self.vehicle_id:
            raise ValidationError('Select a vehicle to continue.')
        if self.vehicle_id not in self._search_available_vehicles():
            raise ValidationError('This vehicle is no longer available for the booking period. Choose another vehicle.')
        if self.journey_id.reservation_id:
            self.journey_id.vehicle_id = self.vehicle_id
        else:
            self.journey_id.booking_vehicle_id = self.vehicle_id
        # Closing the dialog lets the caller reload the booking form, which now
        # shows the selected vehicle. Returning a background action instead
        # would leave this wizard open on top of the refreshed form.
        return {'type': 'ir.actions.act_window_close'}

    def action_full_picture(self):
        self.ensure_one()
        image_field = 'image_1920' if self.vehicle_id.image_1920 else 'rental_image'
        if not self.vehicle_id[image_field]:
            raise ValidationError('This vehicle has no full-size photo.')
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/image/fleet.vehicle/%s/%s' % (self.vehicle_id.id, image_field),
            'target': 'new',
        }


class VehiclePreviewOption(models.TransientModel):
    _name = 'car.rental.vehicle.preview.option'
    _description = 'Vehicle Preview Choice'
    _order = 'license_plate, id'

    preview_id = fields.Many2one(
        'car.rental.vehicle.preview', required=True, ondelete='cascade', index=True)
    vehicle_id = fields.Many2one(
        'fleet.vehicle', required=True, ondelete='cascade')
    name = fields.Char(related='vehicle_id.display_name', string='Vehicle Name')
    license_plate = fields.Char(related='vehicle_id.license_plate')
    model_id = fields.Many2one(related='vehicle_id.model_id', string='Model')
    category_id = fields.Many2one(related='vehicle_id.rental_category_id', string='Category')
    image = fields.Image(related='vehicle_id.rental_image')
    rental_status = fields.Selection(related='vehicle_id.rental_status', string='Availability')
    selected = fields.Boolean(compute='_compute_selected')
    selected_label = fields.Char(compute='_compute_selected', string='Choice')

    @api.depends('preview_id.vehicle_id', 'vehicle_id')
    def _compute_selected(self):
        for option in self:
            is_selected = bool(option.vehicle_id) and option.preview_id.vehicle_id == option.vehicle_id
            option.selected = is_selected
            option.selected_label = 'Selected' if is_selected else ''

    def action_select(self):
        self.ensure_one()
        self.preview_id.write({'vehicle_id': self.vehicle_id.id})
        return self.preview_id._reopen()


class Inspection(models.Model):
    _inherit = 'car.rental.check'

    def action_complete(self):
        result = super().action_complete()
        for inspection in self:
            journey = self.env['car.rental.journey'].sudo().search(
                [('reservation_id', '=', inspection.rental_id.reservation_id.id)], limit=1)
            if journey and journey.step in ('pickup', 'return'):
                if (
                    inspection.kind == 'return'
                    and inspection.rental_id._uses_single_invoice()
                    and not inspection.rental_id.return_charges_confirmed
                ):
                    details = inspection.rental_id._return_charge_details()
                    if (
                        details['late_days'] or details['cleaning_required']
                        or inspection.rental_id.return_collection_service
                    ):
                        return inspection.rental_id.action_return_charge_wizard()
                return journey.action_open()
        return result


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
        invoice = self.sudo().invoice_ids.filtered(
            lambda move: move.rental_invoice_kind == 'rental'
            and move.state == 'posted' and move.move_type == 'out_invoice')[:1]
        if not invoice:
            problems.append('Post the hire and deposit invoice.')
        if self.company_id.rental_require_full_payment and not self.currency_id.is_zero(self.balance_due):
            problems.append('Settle the rental payment required before pickup.')
        if self.currency_id.compare_amounts(self.deposit_held, self.deposit_required) < 0:
            problems.append('Apply eligible deposit credit or pay the full security deposit.')
        return problems

    def _journey_close_blockers(self):
        self.ensure_one()
        problems = []
        invoices = self.sudo().invoice_ids.filtered(lambda move: move.state != 'cancel')
        if self.status != 'returned' or not self.return_inspection_done:
            problems.append('Complete the vehicle return inspection and return action.')
        if self.damage_ids.filtered(lambda case: case.state == 'draft'):
            problems.append('Manager approval of damage required.')
        if self.damage_ids.filtered(lambda case: case.state != 'draft' and case.cost > 0 and (
                not case.invoice_id or case.invoice_id.state != 'posted'
                or not case.invoice_id.currency_id.is_zero(case.invoice_id.amount_residual)
        )):
            problems.append('Settle all approved damage charges.')
        hire_invoice = invoices.filtered(
            lambda move: move.rental_invoice_kind == 'rental' and move.move_type == 'out_invoice')
        if self.amount > 0 and not hire_invoice.filtered(lambda move: move.state == 'posted'):
            problems.append('Create and post the hire invoice.')
        if hire_invoice and any(not self.currency_id.is_zero(move.amount_residual) for move in hire_invoice):
            problems.append('Settle the hire invoice.')
        if invoices.filtered(lambda move: move.state == 'draft'):
            problems.append('Post or cancel draft invoices and credit notes.')
        if not self._uses_single_invoice():
            for kind, amount in [('late', self.late_charge), ('cleaning', self.cleaning_charge)]:
                if amount and not invoices.filtered(
                        lambda move: move.rental_invoice_kind == kind and move.state == 'posted'
                        and move.move_type == 'out_invoice'):
                    problems.append('Create and post the %s invoice.' % kind)
        settlement = invoices.filtered(
            lambda move: move.rental_invoice_kind == 'settlement' and move.move_type == 'out_invoice')
        if any(move.state != 'posted' or not self.currency_id.is_zero(move.amount_residual)
               for move in settlement):
            problems.append('Post and settle the final settlement invoice.')
        legacy_charges = invoices.filtered(
            lambda move: move.rental_invoice_kind in ('late', 'cleaning', 'damage')
            and not self._uses_single_invoice())
        if any(move.state == 'draft' or (
                move.state == 'posted' and not move.currency_id.is_zero(move.amount_residual))
               for move in legacy_charges):
            problems.append('Settle all legacy charge invoices.')
        if not self.currency_id.is_zero(self.deposit_held):
            problems.append('Refund or apply the remaining security deposit.')
        if self.deposit_transaction_ids.filtered(lambda event: event.state == 'draft') or self.payment_ids.filtered(
                lambda payment: payment.state == 'draft'):
            problems.append('Finish or remove unposted deposit transactions and payments.')
        return problems

    def action_close_journey(self):
        require_role(self.env, 'group_rental_accountant')
        for rental in self:
            problems = rental._journey_close_blockers()
            if problems:
                raise ValidationError('\n'.join(problems))
            rental._workflow_write({'status': 'closed', 'closed_on': fields.Datetime.now()})
            rental.message_post(body='Rental cycle closed after return and financial settlement.')
            journey = self.env['car.rental.journey'].sudo().search(
                [('reservation_id', '=', rental.reservation_id.id)], limit=1)
            if journey:
                journey._advance_to('closed')

    def write(self, vals):
        if 'closed_on' in vals:
            raise ValidationError('Use Close Rental to record completion.')
        return super().write(vals)

    def action_booking_journey(self):
        self.ensure_one()
        return self.reservation_id.action_booking_journey()


class Reservation(models.Model):
    _inherit = 'car.rental.reservation'

    def action_booking_journey(self):
        self.ensure_one()
        self.env.cr.execute('SELECT id FROM car_rental_reservation WHERE id = %s FOR UPDATE', [self.id])
        journey = self.env['car.rental.journey'].search(
            [('reservation_id', '=', self.id)], limit=1)
        if not journey:
            journey = self.env['car.rental.journey'].create({
                'company_id': self.company_id.id,
                'reservation_id': self.id,
                'booking_partner_id': self.partner_id.id,
                'booking_destination_id': self.destination_id.id,
                'booking_category_id': self.category_id.id,
                'booking_vehicle_id': self.vehicle_id.id,
                'booking_pickup_datetime': self.pickup_datetime,
                'booking_number_of_days': self.number_of_days,
                'booking_delivery_service': self.delivery_service,
                'booking_delivery_address': self.delivery_address,
                'booking_delivery_fee': self.delivery_fee,
                'booking_collection_service': self.collection_service,
                'booking_collection_address': self.collection_address,
                'booking_collection_fee': self.collection_fee,
            })
            rental = self.rental_ids[:1]
            step = 'quote' if not rental else (
                'closed' if rental.status == 'closed' else
                'settlement' if rental.status == 'returned' else
                'return' if rental.status == 'ongoing' else
                'payment' if rental.agreement_state == 'signed' else 'agreement')
            if step != 'booking':
                super(Journey, journey).write({'step': step})
        return journey.action_open()
