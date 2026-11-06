"""Rental eligibility, monthly references and connected operational defaults."""
from datetime import datetime, time, timedelta
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


class Reservation(models.Model):
    _inherit = 'car.rental.reservation'
    _order = 'pickup_datetime desc, id desc'

    cleaning_fee = fields.Monetary(string='Agreed Dirty Return Fee', readonly=True, copy=False)
    delivery_service = fields.Boolean(string='Customer Delivery Requested', copy=False)
    delivery_address = fields.Char(copy=False)
    delivery_fee = fields.Monetary(copy=False)
    collection_service = fields.Boolean(string='Off-site Collection Requested', copy=False)
    collection_address = fields.Char(copy=False)
    collection_fee = fields.Monetary(copy=False)
    quote_service_total = fields.Monetary(
        compute='_compute_quote_service_total', string='Optional Service Charges')
    quote_total = fields.Monetary(compute='_compute_quote_total', string='Total Quotation')
    reference = fields.Char(default=False, required=True, copy=False, tracking=True)
    number_of_days = fields.Integer(string='Rental Days (24-hour periods)', default=1)
    customer_deposit_credit = fields.Monetary(
        compute='_compute_customer_deposit_credit', string='Customer Deposit Credit Available')

    @api.depends(
        'delivery_service', 'delivery_fee', 'collection_service', 'collection_fee',
        'tax_id', 'currency_id')
    def _compute_quote_service_total(self):
        for reservation in self:
            total = 0
            for enabled, fee in (
                (reservation.delivery_service, reservation.delivery_fee),
                (reservation.collection_service, reservation.collection_fee),
            ):
                if not enabled:
                    continue
                totals = reservation.tax_id.compute_all(
                    fee, currency=reservation.currency_id, quantity=1
                ) if reservation.tax_id else {'total_included': fee}
                total += totals['total_included']
            reservation.quote_service_total = total

    @api.depends('amount', 'quote_service_total', 'deposit_required')
    def _compute_quote_total(self):
        for reservation in self:
            reservation.quote_total = (
                reservation.amount + reservation.quote_service_total
                + reservation.deposit_required
            )

    @api.constrains(
        'delivery_service', 'delivery_address', 'delivery_fee',
        'collection_service', 'collection_address', 'collection_fee')
    def _check_quote_services(self):
        for reservation in self:
            for enabled, location, amount, label in (
                (reservation.delivery_service, reservation.delivery_address,
                 reservation.delivery_fee, 'Customer delivery'),
                (reservation.collection_service, reservation.collection_address,
                 reservation.collection_fee, 'Off-site collection'),
            ):
                if enabled and (not location or amount <= 0):
                    raise ValidationError(
                        '%s requires an address and a positive charge.' % label)
                if amount < 0:
                    raise ValidationError('Optional service charges cannot be negative.')
            if reservation.status != 'draft' and (
                not reservation.delivery_service and reservation.delivery_fee
                or not reservation.collection_service and reservation.collection_fee
            ):
                raise ValidationError('Clear an optional service amount when that service is not selected.')

    @api.depends('partner_id', 'company_id')
    def _compute_customer_deposit_credit(self):
        Rentals = self.env['car.rental.rental']
        for reservation in self:
            sources = Rentals._deposit_credit_sources(
                reservation.partner_id, reservation.company_id)
            reservation.customer_deposit_credit = sum(sources.mapped('deposit_held'))

    @api.constrains('reference', 'company_id')
    def _check_reference(self):
        validate_reference(self)

    @api.constrains('pickup_datetime', 'expected_return_datetime', 'number_of_days')
    def _check_dates(self):
        for record in self:
            if record.pickup_datetime and record.expected_return_datetime and record.expected_return_datetime <= record.pickup_datetime:
                raise ValidationError('Return date and time must be after pickup date and time.')
            if record.pickup_datetime and record.expected_return_datetime and record.number_of_days < 1:
                raise ValidationError('A rental must be at least one 24-hour rental day.')

    @api.onchange('pickup_datetime', 'number_of_days')
    def _onchange_booking_times(self):
        if self.pickup_datetime and self.number_of_days > 0:
            self.expected_return_datetime = self.pickup_datetime + timedelta(days=self.number_of_days)
        else:
            self.expected_return_datetime = False
        self.start_date = self.pickup_datetime.date() if self.pickup_datetime else False
        self.end_date = self.expected_return_datetime.date() if self.expected_return_datetime else False
        self._onchange_pricing()

    @api.depends('category_id', 'pickup_datetime', 'expected_return_datetime', 'company_id')
    def _compute_available(self):
        for record in self:
            candidates = self.env['fleet.vehicle'].search([
                ('company_id', '=', record.company_id.id), ('rental_category_id', '=', record.category_id.id),
                ('rental_status', 'in', ['available', 'reserved', 'rented']), ('license_plate', '!=', False),
            ]) if record.category_id else self.env['fleet.vehicle']
            conflicts = self.search([('id', '!=', record._origin.id or 0), ('vehicle_id', 'in', candidates.ids),
                                     ('status', '!=', 'cancelled'), ('pickup_datetime', '<', record.expected_return_datetime),
                                     ('expected_return_datetime', '>', record.pickup_datetime)]) if record.pickup_datetime and record.expected_return_datetime else self.browse()
            record.available_vehicle_ids = candidates - conflicts.mapped('vehicle_id')

    @api.constrains('vehicle_id', 'pickup_datetime', 'expected_return_datetime', 'status')
    def _check_vehicle_availability(self):
        for record in self:
            if record.status == 'cancelled' or not record.vehicle_id or not record.pickup_datetime or not record.expected_return_datetime:
                continue
            self.env.cr.execute('UPDATE fleet_vehicle SET id = id WHERE id = %s', [record.vehicle_id.id])
            if self.search_count([('id', '!=', record.id), ('vehicle_id', '=', record.vehicle_id.id), ('status', '!=', 'cancelled'),
                                  ('pickup_datetime', '<', record.expected_return_datetime), ('expected_return_datetime', '>', record.pickup_datetime)]):
                raise ValidationError('This vehicle is already allocated during these pickup/return times.')

    @staticmethod
    def _sync_times(vals, current=None, creating=False):
        vals = dict(vals)
        if vals.get('start_date') and not vals.get('pickup_datetime'):
            vals['pickup_datetime'] = datetime.combine(fields.Date.to_date(vals['start_date']), time(8))
        if vals.get('end_date') and not vals.get('expected_return_datetime'):
            vals['expected_return_datetime'] = datetime.combine(fields.Date.to_date(vals['end_date']), time(8))

        pickup = fields.Datetime.to_datetime(vals.get('pickup_datetime')) if vals.get('pickup_datetime') else (
            current.pickup_datetime if current else False)
        if 'number_of_days' in vals:
            days = vals['number_of_days']
            if pickup and days and days > 0:
                vals['expected_return_datetime'] = pickup + timedelta(days=days)
        elif vals.get('expected_return_datetime'):
            expected = fields.Datetime.to_datetime(vals['expected_return_datetime'])
            if pickup and expected > pickup:
                vals['number_of_days'] = ceil((expected - pickup).total_seconds() / 86400)
        elif pickup and current and current.number_of_days > 0 and 'pickup_datetime' in vals:
            vals['expected_return_datetime'] = pickup + timedelta(days=current.number_of_days)
        elif creating and pickup:
            days = vals.get('number_of_days', 1)
            if days > 0:
                vals['expected_return_datetime'] = pickup + timedelta(days=days)

        if vals.get('pickup_datetime'):
            vals['start_date'] = fields.Datetime.to_datetime(vals['pickup_datetime']).date()
        if vals.get('expected_return_datetime'):
            vals['end_date'] = fields.Datetime.to_datetime(vals['expected_return_datetime']).date()
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        normalized = []
        for values in vals_list:
            vals = self._sync_times(values, creating=True)
            if {'deposit_required', 'deposit_ratio', 'cleaning_fee'}.intersection(vals):
                raise ValidationError('Deposits and cleaning fees are calculated from the approved pricing rule.')
            vals['reference'] = (vals.get('reference') or '').strip()
            if not vals['reference'] or vals['reference'].lower() == 'new':
                company = self.env['res.company'].browse(vals.get('company_id')) or self.env.company
                date = vals.get('start_date') or fields.Date.context_today(self)
                vals['reference'] = monthly_reference(self.env, self._name, 'RES', company, date)
            normalized.append(vals)
        return super().create(normalized)

    def write(self, vals):
        if {'deposit_required', 'deposit_ratio', 'cleaning_fee'}.intersection(vals):
            raise ValidationError('Deposits and cleaning fees are calculated from the approved pricing rule.')
        quote_fields = {
            'delivery_service', 'delivery_address', 'delivery_fee',
            'collection_service', 'collection_address', 'collection_fee',
        }
        if quote_fields.intersection(vals) and any(
            record.status != 'draft' or record.rental_ids for record in self
        ):
            raise ValidationError(
                'Optional delivery and collection services are locked when the reservation is confirmed or rented.')
        vals = dict(vals)
        if 'reference' in vals:
            vals['reference'] = (vals['reference'] or '').strip()
        if {'start_date', 'end_date', 'pickup_datetime', 'expected_return_datetime', 'number_of_days'}.intersection(vals):
            for record in self:
                record_vals = self._sync_times(vals, current=record)
                super(Reservation, record).write(record_vals)
            return True
        return super().write(vals)

    @api.constrains('quoted_daily_rate', 'deposit_ratio', 'status')
    def _check_deposit_policy(self):
        for record in self:
            if record.status == 'confirmed' and (not 0.5 <= record.deposit_ratio <= 1 or record.deposit_required < record.quoted_daily_rate * 0.5 - 0.005):
                raise ValidationError('A confirmed reservation must hold a deposit of at least 50% of its agreed daily rate.')

    def action_confirm(self):
        for record in self:
            if not record.pickup_datetime or not record.expected_return_datetime or record.number_of_days < 1:
                raise ValidationError('Select a pickup date and time and enter at least one rental day.')
            record.partner_id.sudo()._check_rental_eligibility(
                record.pickup_datetime, record.expected_return_datetime)
        return super().action_confirm()

    def action_refresh_cleaning_fee(self):
        require_role(self.env, 'group_rental_manager')
        raise ValidationError(
            'Pricing-rule cleaning fees are retired. Configure the cleaning product and enter new-flow charges at return.')


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
        self.agreement_signed_by = self.partner_id.display_name if self.partner_id else False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'deposit_required' in vals or 'cleaning_charge' in vals:
                raise ValidationError('Use the rental workflow to calculate deposits and charges.')
            reservation = self.env['car.rental.reservation'].browse(vals.get('reservation_id'))
            vals['reference'] = (vals.get('reference') or '').strip()
            if reservation:
                vals.setdefault('agreement_signed_by', reservation.partner_id.display_name)
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
            rental.partner_id.sudo()._check_rental_eligibility(
                rental.reservation_id.pickup_datetime, rental.expected_return_datetime)
        result = super().action_start_rental()
        for rental in self:
            pickup = rental.inspection_ids.filtered(lambda c: c.kind == 'pickup' and c.state == 'done')[:1]
            # Internal write keeps the recorded inspection's actual handover time.
            rental._operational_handover_time(pickup.checked_on)
        return result

    def _operational_handover_time(self, date):
        self._workflow_write({'actual_pickup_datetime': date})

    def action_return_vehicle(self):
        for rental in self:
            check = rental.inspection_ids.filtered(lambda c: c.kind == 'return' and c.state == 'done')[:1]
            if rental._uses_single_invoice() and not rental.return_charges_confirmed:
                details = rental._return_charge_details()
                if details['late_days'] and not rental.company_id.cr_late_product_id:
                    raise ValidationError('Configure the late-return service product in Car Rental Settings.')
                if details['cleaning_required'] and not rental.company_id.cr_cleaning_product_id:
                    raise ValidationError('Configure the dirty-return cleaning product in Car Rental Settings.')
                if rental.return_collection_service and not rental.company_id.cr_collection_product_id:
                    raise ValidationError('Configure the vehicle collection service product in Car Rental Settings.')
                if details['late_days'] or details['cleaning_required'] or rental.return_collection_service:
                    return rental.action_return_charge_wizard()
        result = super().action_return_vehicle()
        for rental in self:
            check = rental.inspection_ids.filtered(lambda c: c.kind == 'return' and c.state == 'done')[:1]
            if rental._uses_single_invoice():
                charge = rental.cleaning_charge
            else:
                charge = rental.reservation_id.cleaning_fee if check and not check.clean else 0
                rental._workflow_write({'cleaning_charge': charge})
            if charge and not rental._uses_single_invoice():
                rental.sudo().action_cleaning_invoice()
        return result

    def action_return_charge_wizard(self):
        self.ensure_one()
        if self.status != 'ongoing' or not self.return_inspection_done:
            raise ValidationError('Complete the return inspection before confirming return charges.')
        return {
            'type': 'ir.actions.act_window',
            'name': 'Confirm Return Charges',
            'res_model': 'car.rental.return.charge.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_rental_id': self.id},
        }

    def action_cleaning_invoice(self):
        self.ensure_one()
        if self._uses_single_invoice():
            raise ValidationError('Cleaning charges for this booking are included in its final settlement invoice.')
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

    clean = fields.Boolean(string='Vehicle Clean', default=False)
    fuel_level = fields.Selection(selection_add=[('blinking', 'Blinking Bar')] +
                                  [('bar_%s' % i, '%s Bar%s' % (i, '' if i == 1 else 's')) for i in range(1, 9)],
                                  ondelete={key: 'set empty' for key in ['blinking'] + ['bar_%s' % i for i in range(1, 9)]})

    @api.onchange('rental_id')
    def _onchange_acknowledgement_name(self):
        self.acknowledged_by = self.rental_id.partner_id.display_name if self.rental_id else False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('rental_id'):
                rental = self.env['car.rental.rental'].browse(vals['rental_id'])
                vals.setdefault('acknowledged_by', rental.partner_id.display_name)
        return super().create(vals_list)

class Move(models.Model):
    _inherit = 'account.move'
    rental_invoice_kind = fields.Selection(selection_add=[('cleaning', 'Cleaning')])


class Deposit(models.Model):
    _inherit = 'car.rental.deposit.transaction'
    charge_invoice_id = fields.Many2one('account.move', string='Charge Invoice', check_company=True)

    def action_post(self):
        require_role(self.env, 'group_rental_accountant')
        for event in self:
            minimum = event.rental_id.reservation_id.quoted_daily_rate * 0.5
            if (
                event.kind == 'collect'
                and event.rental_id.deposit_held < minimum
                and event.rental_id.deposit_held + event.amount < minimum - 0.005
            ):
                raise ValidationError('Initial security deposit collection cannot be below 50% of the agreed daily rate.')
        return super().action_post()
