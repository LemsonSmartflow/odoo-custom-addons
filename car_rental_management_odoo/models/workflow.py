from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.float_utils import float_compare, float_is_zero


def window(name, model, domain=None, context=None, res_id=None):
    action = {
        'type': 'ir.actions.act_window', 'name': name,
        'res_model': model, 'view_mode': 'form' if res_id else 'list,form',
        'domain': domain or [], 'context': context or {},
    }
    if res_id:
        action['res_id'] = res_id
    return action


class Vehicle(models.Model):
    _inherit = 'car.rental.vehicle'

    reservation_ids = fields.One2many('car.rental.reservation', 'vehicle_id')
    rental_ids = fields.One2many('car.rental.rental', 'vehicle_id')
    reservation_count = fields.Integer(compute='_compute_counts')
    rental_count = fields.Integer(compute='_compute_counts')

    @api.depends('reservation_ids', 'rental_ids')
    def _compute_counts(self):
        for record in self:
            record.reservation_count = len(record.reservation_ids)
            record.rental_count = len(record.rental_ids)

    def action_reservations(self):
        self.ensure_one()
        return window('Vehicle Reservations', 'car.rental.reservation',
                      [('vehicle_id', '=', self.id)], {'default_vehicle_id': self.id})

    def action_rentals(self):
        self.ensure_one()
        return window('Vehicle Rentals', 'car.rental.rental', [('vehicle_id', '=', self.id)])

    def action_book(self):
        self.ensure_one()
        if self.status == 'maintenance':
            raise ValidationError('A vehicle in maintenance cannot be reserved.')
        return dict(window('New Reservation', 'car.rental.reservation',
                           context={'default_vehicle_id': self.id}), view_mode='form')


class Customer(models.Model):
    _inherit = 'car.rental.customer'

    reservation_ids = fields.One2many('car.rental.reservation', 'customer_id')
    rental_ids = fields.One2many('car.rental.rental', 'customer_id')
    reservation_count = fields.Integer(compute='_compute_counts')
    rental_count = fields.Integer(compute='_compute_counts')

    @api.depends('reservation_ids', 'rental_ids')
    def _compute_counts(self):
        for record in self:
            record.reservation_count = len(record.reservation_ids)
            record.rental_count = len(record.rental_ids)

    @api.depends('first_name', 'last_name')
    def _compute_display_name(self):
        for record in self:
            record.display_name = ' '.join(filter(None, [record.first_name, record.last_name]))

    def action_reservations(self):
        self.ensure_one()
        return window('Customer Reservations', 'car.rental.reservation',
                      [('customer_id', '=', self.id)], {'default_customer_id': self.id})

    def action_rentals(self):
        self.ensure_one()
        return window('Customer Rentals', 'car.rental.rental', [('customer_id', '=', self.id)])

    def action_book(self):
        self.ensure_one()
        return dict(window('New Reservation', 'car.rental.reservation',
                           context={'default_customer_id': self.id}), view_mode='form')


class Reservation(models.Model):
    _inherit = 'car.rental.reservation'

    vehicle_image = fields.Image(related='vehicle_id.image_1920', readonly=True)
    daily_price = fields.Float(related='quoted_daily_rate', readonly=True)
    rental_ids = fields.One2many('car.rental.rental', 'reservation_id')
    rental_count = fields.Integer(compute='_compute_rental_count')

    @api.depends('rental_ids')
    def _compute_rental_count(self):
        for record in self:
            record.rental_count = len(record.rental_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('reference', 'New') == 'New':
                vals['reference'] = self.env['ir.sequence'].next_by_code('car.rental.reservation') or 'New'
        return super().create(vals_list)

    def action_create_rental(self):
        self.ensure_one()
        if self.status != 'confirmed':
            raise ValidationError('Confirm the reservation before creating a rental.')
        rental = self.rental_ids[:1]
        if not rental:
            rental = self.env['car.rental.rental'].create({
                'reservation_id': self.id, 'initial_mileage': self.vehicle_id.mileage,
            })
        return window('Rental', 'car.rental.rental', res_id=rental.id)

    def action_rentals(self):
        self.ensure_one()
        if len(self.rental_ids) == 1:
            return window('Rental', 'car.rental.rental', res_id=self.rental_ids.id)
        return window('Rentals', 'car.rental.rental', [('reservation_id', '=', self.id)],
                      {'default_reservation_id': self.id})

    def write(self, vals):
        protected = {'customer_id', 'vehicle_id', 'start_date', 'end_date', 'status'}
        if protected.intersection(vals) and any(self.mapped('rental_ids')):
            raise ValidationError('This reservation is linked to a rental and can no longer be changed.')
        return super().write(vals)


class Rental(models.Model):
    _inherit = 'car.rental.rental'

    vehicle_image = fields.Image(related='vehicle_id.image_1920', readonly=True)
    payment_ids = fields.One2many('car.rental.payment', 'rental_id', string='Payments')
    payment_count = fields.Integer(compute='_compute_payment_totals', store=True)
    paid_total = fields.Float(string='Total Paid', compute='_compute_payment_totals', store=True)
    balance_due = fields.Float(string='Balance Due', compute='_compute_payment_totals', store=True)
    payment_status = fields.Selection([
        ('unpaid', 'Unpaid'), ('partial', 'Partially Paid'), ('paid', 'Paid'),
    ], compute='_compute_payment_totals', store=True, string='Payment Status')

    @api.depends('amount', 'currency_id', 'payment_ids.paid_amount', 'payment_ids.ledger_state', 'payment_ids.account_move_id.state', 'payment_ids.account_move_id.reversal_move_ids.state',
                 'invoice_ids.state', 'invoice_ids.rental_invoice_kind', 'invoice_ids.move_type', 'invoice_ids.amount_total', 'invoice_ids.amount_residual')
    def _compute_payment_totals(self):
        for record in self:
            paid = sum(record.payment_ids.filtered(lambda p: p.ledger_state == 'legacy' or (p.ledger_state == 'posted' and p.account_move_id.state == 'posted' and not p.account_move_id.reversal_move_ids.filtered(lambda m: m.state == 'posted'))).mapped('paid_amount'))
            invoices = record.invoice_ids.filtered(lambda m: m.state == 'posted' and m.move_type == 'out_invoice' and m.rental_invoice_kind == 'rental')
            if invoices:
                # Both rental receipts and standard invoice payments reconcile the
                # same receivable: use its settlement once, without double counting.
                paid = sum(m.amount_total - m.amount_residual for m in invoices)
            record.payment_count = len(record.payment_ids)
            record.paid_total = paid
            currency = record.currency_id or self.env.company.currency_id
            record.balance_due = currency.round(max(record.amount - paid, 0.0))
            record.payment_status = (
                'paid' if float_compare(paid, record.amount, precision_digits=2) >= 0
                else 'unpaid' if float_is_zero(paid, precision_digits=2) else 'partial'
            )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('reference', 'New') == 'New':
                vals['reference'] = self.env['ir.sequence'].next_by_code('car.rental.rental') or 'New'
            if 'initial_mileage' not in vals and vals.get('reservation_id'):
                vals['initial_mileage'] = self.env['car.rental.reservation'].browse(vals['reservation_id']).vehicle_id.mileage
        return super().create(vals_list)

    @api.constrains('reservation_id')
    def _check_reservation(self):
        for record in self:
            if record.reservation_id.status != 'confirmed':
                raise ValidationError('Only confirmed reservations can become rentals.')
            if self.search_count([('reservation_id', '=', record.reservation_id.id), ('id', '!=', record.id)]):
                raise ValidationError('This reservation already has a rental. Open the existing rental instead.')

    @api.onchange('reservation_id')
    def _onchange_reservation(self):
        self.initial_mileage = self.reservation_id.vehicle_id.mileage

    def write(self, vals):
        if 'reservation_id' in vals and any(record.payment_ids or record.status != 'draft' for record in self):
            raise ValidationError('A rental with payments or an active rental cannot change its reservation.')
        return super().write(vals)

    def action_record_payment(self):
        self.ensure_one()
        if float_is_zero(self.balance_due, precision_digits=2):
            raise ValidationError('This rental is already fully paid.')
        return dict(window('Record Payment', 'car.rental.payment', context={
            'default_rental_id': self.id, 'default_paid_amount': self.balance_due,
        }), view_mode='form', target='new')

    def action_payments(self):
        self.ensure_one()
        return window('Rental Payments', 'car.rental.payment', [('rental_id', '=', self.id)],
                      {'default_rental_id': self.id, 'default_paid_amount': self.balance_due})

    def action_reservation(self):
        self.ensure_one()
        return window('Reservation', 'car.rental.reservation', res_id=self.reservation_id.id)

    def action_start_rental(self):
        if any(record.status != 'draft' for record in self):
            raise ValidationError('Only draft rentals can be started.')
        if any(record.vehicle_id.status != 'available' for record in self):
            raise ValidationError('The vehicle must be available before starting a rental.')
        return super().action_start_rental()

    def action_return_vehicle(self):
        if any(record.status != 'ongoing' for record in self):
            raise ValidationError('Only ongoing rentals can be returned.')
        return super().action_return_vehicle()


class Payment(models.Model):
    _inherit = 'car.rental.payment'

    customer_id = fields.Many2one(related='rental_id.customer_id', readonly=True)
    vehicle_id = fields.Many2one(related='rental_id.vehicle_id', readonly=True)
    vehicle_image = fields.Image(related='vehicle_id.image_1920', readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('reference', 'New') == 'New':
                vals['reference'] = self.env['ir.sequence'].next_by_code('car.rental.payment') or 'New'
        return super().create(vals_list)

    @api.depends('rental_id.balance_due')
    def _compute_remaining_amount(self):
        for record in self:
            record.remaining_amount = record.rental_id.balance_due

    @api.depends('rental_id.payment_status')
    def _compute_status(self):
        for record in self:
            record.status = record.rental_id.payment_status

    @api.constrains('paid_amount', 'rental_id', 'total_amount')
    def _check_paid_amount(self):
        for record in self:
            if record.paid_amount <= 0:
                raise ValidationError('Enter a payment amount greater than zero.')
            # Serialize payment changes for the same rental, including simultaneous requests.
            # A write also makes a stale repeatable-read transaction retry in Odoo.
            self.env.cr.execute('UPDATE car_rental_rental SET id = id WHERE id = %s', [record.rental_id.id])
            payments = self.search([('rental_id', '=', record.rental_id.id)])
            payments.invalidate_recordset(['paid_amount'])
            if float_compare(sum(payments.mapped('paid_amount')), record.total_amount, precision_digits=2) > 0:
                raise ValidationError('The combined payments cannot exceed the rental amount.')

    @api.onchange('rental_id')
    def _onchange_rental(self):
        if not self._origin.id:
            self.paid_amount = self.rental_id.balance_due

    def action_rental(self):
        self.ensure_one()
        return window('Rental', 'car.rental.rental', res_id=self.rental_id.id)


class Dashboard(models.Model):
    _inherit = 'car.rental.dashboard'

    confirmed_reservations = fields.Integer(compute='_compute_dashboard')
    outstanding_balance = fields.Float(compute='_compute_dashboard', string='Outstanding Balance')

    def _compute_dashboard(self):
        super()._compute_dashboard()
        reservations = self.env['car.rental.reservation'].search_count([('status', '=', 'confirmed')])
        balance = sum(self.env['car.rental.rental'].search([]).mapped('balance_due'))
        for record in self:
            record.confirmed_reservations = reservations
            record.outstanding_balance = balance

    def action_vehicles(self):
        return dict(window('Vehicle Gallery', 'car.rental.vehicle'), view_mode='kanban,list,form')

    def action_available(self):
        return dict(window('Available Vehicles', 'car.rental.vehicle', [('status', '=', 'available')]), view_mode='kanban,list,form')

    def action_customers(self):
        return window('Customers', 'car.rental.customer')

    def action_reservations(self):
        return window('Confirmed Reservations', 'car.rental.reservation', [('status', '=', 'confirmed')])

    def action_rentals(self):
        return window('Ongoing Rentals', 'car.rental.rental', [('status', '=', 'ongoing')])

    def action_payments(self):
        return window('Payments', 'car.rental.payment')

    def action_balances(self):
        return window('Rentals With Outstanding Balance', 'car.rental.rental', [('balance_due', '>', 0)])
