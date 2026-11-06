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
    _inherit = 'fleet.vehicle'

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
        if self.rental_status == 'maintenance':
            raise ValidationError('A vehicle in maintenance cannot be reserved.')
        return dict(window('New Reservation', 'car.rental.reservation',
                           context={'default_vehicle_id': self.id}), view_mode='form')


class Reservation(models.Model):
    _inherit = 'car.rental.reservation'

    vehicle_image = fields.Image(related='vehicle_id.rental_image', readonly=True)
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
                'reservation_id': self.id, 'initial_mileage': self.vehicle_id.odometer,
            })
        return window('Rental', 'car.rental.rental', res_id=rental.id)

    def action_rentals(self):
        self.ensure_one()
        if len(self.rental_ids) == 1:
            return window('Rental', 'car.rental.rental', res_id=self.rental_ids.id)
        return window('Rentals', 'car.rental.rental', [('reservation_id', '=', self.id)],
                      {'default_reservation_id': self.id})

    def unlink(self):
        if any(self.mapped('rental_ids')):
            raise ValidationError(
                'This reservation has linked rental history and cannot be deleted. '
                'Cancel the booking to release the vehicle, then create a new booking to start over.')
        return super().unlink()

    def write(self, vals):
        protected = {'partner_id', 'vehicle_id', 'start_date', 'end_date', 'status'}
        cancellation = vals == {'status': 'cancelled'} and all(r.status == 'cancelled' for r in self.mapped('rental_ids'))
        if protected.intersection(vals) and any(self.mapped('rental_ids')) and not cancellation:
            raise ValidationError('This reservation is linked to a rental and can no longer be changed.')
        return super().write(vals)


class Rental(models.Model):
    _inherit = 'car.rental.rental'

    vehicle_image = fields.Image(related='vehicle_id.rental_image', readonly=True)
    payment_ids = fields.One2many('account.payment', 'car_rental_id', string='Payments')
    payment_count = fields.Integer(compute='_compute_payment_totals', store=True)
    paid_total = fields.Monetary(string='Total Paid', compute='_compute_payment_totals', store=True)
    balance_due = fields.Monetary(string='Balance Due', compute='_compute_payment_totals', store=True)
    payment_status = fields.Selection([
        ('unpaid', 'Unpaid'), ('partial', 'Partially Paid'), ('paid', 'Paid'),
    ], compute='_compute_payment_totals', store=True, string='Payment Status')

    @api.depends('amount', 'currency_id', 'payment_ids.amount', 'payment_ids.state', 'payment_ids.rental_legacy', 'payment_ids.move_id.reversal_move_ids.state',
                 'invoice_ids.state', 'invoice_ids.rental_invoice_kind', 'invoice_ids.move_type',
                 'invoice_ids.amount_total', 'invoice_ids.amount_residual',
                 'invoice_ids.invoice_line_ids.rental_deposit_line', 'invoice_ids.invoice_line_ids.price_total',
                 'reservation_id.deposit_required', 'reservation_id.quote_service_total')
    def _compute_payment_totals(self):
        for record in self:
            paid = sum(record.payment_ids.filtered(lambda p: p.rental_legacy or (p.state == 'paid' and not p.move_id.reversal_move_ids.filtered(lambda m: m.state == 'posted'))).mapped('amount'))
            invoices = record.invoice_ids.filtered(lambda m: m.state == 'posted' and m.move_type == 'out_invoice' and m.rental_invoice_kind == 'rental')
            if invoices:
                paid = sum(m.amount_total - m.amount_residual for m in invoices)
            record.payment_count = len(record.payment_ids)
            record.paid_total = paid
            currency = record.currency_id or self.env.company.currency_id
            deposit_line_total = sum(
                line.price_total
                for move in invoices
                for line in move.invoice_line_ids.filtered('rental_deposit_line')
            )
            deposit_paid = min(deposit_line_total, paid)
            hire_paid = paid - deposit_paid if deposit_line_total else paid
            charge_total = record.reservation_id.quote_service_total
            record.balance_due = currency.round(
                max(record.amount + charge_total - hire_paid, 0.0))
            hire_paid = max(min(hire_paid, record.amount), 0.0)
            record.payment_status = (
                'paid' if float_compare(hire_paid, record.amount, precision_rounding=currency.rounding) >= 0
                else 'unpaid' if float_is_zero(hire_paid, precision_rounding=currency.rounding) else 'partial'
            )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('reference', 'New') == 'New':
                vals['reference'] = self.env['ir.sequence'].next_by_code('car.rental.rental') or 'New'
            if 'initial_mileage' not in vals and vals.get('reservation_id'):
                vals['initial_mileage'] = self.env['car.rental.reservation'].browse(vals['reservation_id']).vehicle_id.odometer
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
        self.initial_mileage = self.reservation_id.vehicle_id.odometer

    def write(self, vals):
        if 'reservation_id' in vals and any(record.payment_ids or record.status != 'draft' for record in self):
            raise ValidationError('A rental with payments or an active rental cannot change its reservation.')
        return super().write(vals)

    def action_payments(self):
        self.ensure_one()
        return window('Rental Payments', 'account.payment', [('car_rental_id', '=', self.id)],
                      {'default_car_rental_id': self.id})

    def action_reservation(self):
        self.ensure_one()
        return window('Reservation', 'car.rental.reservation', res_id=self.reservation_id.id)

    def action_start_rental(self):
        if any(record.status != 'draft' for record in self):
            raise ValidationError('Only draft rentals can be started.')
        if any(record.vehicle_id.rental_status != 'available' for record in self):
            raise ValidationError('The vehicle must be available before starting a rental.')
        return super().action_start_rental()

    def action_return_vehicle(self):
        if any(record.status != 'ongoing' for record in self):
            raise ValidationError('Only ongoing rentals can be returned.')
        return super().action_return_vehicle()


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
        return dict(window('Vehicle Gallery', 'fleet.vehicle'), view_mode='kanban,list,form')

    def action_available(self):
        return dict(window('Available Vehicles', 'fleet.vehicle', [('rental_status', '=', 'available')]), view_mode='kanban,list,form')

    def action_customers(self):
        return window('Customers', 'res.partner')

    def action_reservations(self):
        return window('Confirmed Reservations', 'car.rental.reservation', [('status', '=', 'confirmed')])

    def action_rentals(self):
        return window('Ongoing Rentals', 'car.rental.rental', [('status', '=', 'ongoing')])

    def action_payments(self):
        return window('Payments', 'account.payment', [('car_rental_id', '!=', False)])

    def action_balances(self):
        return window('Rentals With Outstanding Balance', 'car.rental.rental', [('balance_due', '>', 0)])
