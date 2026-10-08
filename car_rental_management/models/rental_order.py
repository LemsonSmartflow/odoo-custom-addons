# Part of Odoo. See LICENSE file for full copyright and licensing details.

import math
from datetime import datetime, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

RENTAL_STATES = [
    ('draft', 'Draft'),
    ('quotation', 'Quotation'),
    ('confirmed', 'Confirmed/Reserved'),
    ('active', 'Picked Up / Active Rental'),
    ('returned', 'Returned - Inspection Pending'),
    ('settled', 'Settled'),
    ('closed', 'Closed'),
    ('cancelled', 'Cancelled'),
]

INSPECTION_STATUSES = [
    ('none', 'No Inspection'),
    ('pickup_done', 'Pickup Inspection Done'),
    ('return_done', 'Return Inspection Done'),
]

PRICING_FIELDS = {'rental_daily_rate', 'pricing_rule_id', 'pricing_override', 'pricing_override_reason', 'security_deposit_amount'}


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    rental_state = fields.Selection(
        selection=RENTAL_STATES, string='Rental Status', default='draft', tracking=True, copy=False,
        help='Draft > Quotation > Confirmed/Reserved > Picked Up > Active Rental > Returned > Settled > Closed.')
    rental_destination_id = fields.Many2one(
        'car.rental.destination', string='Rental Destination', tracking=True, check_company=True)
    rental_vehicle_category_id = fields.Many2one(
        'car.rental.vehicle.category', string='Vehicle Category', tracking=True, check_company=True)
    allocated_vehicle_id = fields.Many2one(
        'fleet.vehicle', string='Allocated Vehicle', tracking=True, check_company=True, copy=False,
        domain="[('rental_status', 'in', ('available', 'reserved')), '|', ('rental_category_id', '=', False), ('rental_category_id', '=', rental_vehicle_category_id)]")
    pricing_rule_id = fields.Many2one('car.rental.pricing.rule', string='Pricing Rule', readonly=True, copy=False)
    rental_daily_rate = fields.Monetary(
        string='Daily Rate', currency_field='currency_id', compute='_compute_rental_pricing',
        store=True, readonly=False, copy=False,
        help='Applicable daily rate. Confirmed orders keep a snapshot of the rate used at confirmation.')
    rental_days = fields.Float(
        string='Rental Days', compute='_compute_rental_pricing', store=True, readonly=False,
        help='Billable rental days (inclusive of pickup and return day).')
    security_deposit_amount = fields.Monetary(
        string='Security Deposit', currency_field='currency_id', compute='_compute_rental_pricing',
        store=True, readonly=False, copy=False,
        help='Refundable deposit. Current policy: one day of the applicable rental rate. It is a liability, not rental revenue.')
    deposit_status = fields.Selection(
        selection=[
            ('none', 'N/A'),
            ('not_required', 'Not Required'),
            ('required', 'Required'),
            ('collected', 'Collected'),
            ('partially_applied', 'Partially Applied'),
            ('refund_pending', 'Refund Pending'),
            ('refunded', 'Refunded'),
            ('forfeited', 'Forfeited'),
        ],
        string='Deposit Status', compute='_compute_deposit_status', store=True, copy=False)
    rental_pickup_date = fields.Date(string='Pickup Date', tracking=True)
    rental_return_date = fields.Date(string='Return Date', tracking=True)
    pickup_location_id = fields.Many2one('car.rental.destination', string='Pickup Location')
    return_location_id = fields.Many2one('car.rental.destination', string='Return Location')
    actual_pickup_datetime = fields.Datetime(string='Actual Pickup', copy=False)
    actual_return_datetime = fields.Datetime(string='Actual Return', copy=False)
    pickup_mileage = fields.Float(string='Pickup Mileage (km)', copy=False)
    return_mileage = fields.Float(string='Return Mileage (km)', copy=False)
    inspection_status = fields.Selection(
        selection=INSPECTION_STATUSES, string='Inspection Status', default='none', copy=False)
    damage_detected = fields.Boolean(string='Damage Detected', copy=False)
    pricing_override = fields.Boolean(string='Pricing Override', copy=False)
    pricing_override_reason = fields.Text(string='Override Reason', copy=False)
    pricing_override_user_id = fields.Many2one('res.users', string='Override Approved By', copy=False, readonly=True)
    cross_border_approved = fields.Boolean(
        string='Cross Border Approved',
        help='Manager approval for cross-border destinations.')
    inspection_ids = fields.One2many('car.rental.inspection', 'rental_order_id', string='Inspection Lines')
    inspection_count = fields.Integer(compute='_compute_rental_counts', string='Inspections')
    damage_ids = fields.One2many('car.rental.damage', 'rental_order_id', string='Damage Assessments')
    damage_count = fields.Integer(compute='_compute_rental_counts', string='Damages')
    deposit_ids = fields.One2many('car.rental.deposit', 'rental_order_id', string='Deposit Records')
    deposit_count = fields.Integer(compute='_compute_rental_counts', string='Deposits')
    charge_ids = fields.One2many('car.rental.charge', 'rental_order_id', string='Additional Charges')
    charge_count = fields.Integer(compute='_compute_rental_counts', string='Charges')
    is_late_return = fields.Boolean(
        string='Overdue', compute='_compute_is_late_return', search='_search_is_late_return')

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------

    @api.depends('rental_pickup_date', 'rental_return_date', 'rental_days')
    def _compute_is_late_return(self):
        now = fields.Datetime.now()
        for order in self:
            order.is_late_return = bool(
                order.rental_state in ('confirmed', 'active')
                and order.rental_return_date
                and order.rental_return_date < now.date(),
            )

    def _search_is_late_return(self, operator, value):
        today = fields.Datetime.now().date()
        date_op = '<' if (operator == '=' and value) or (operator == '!=' and not value) else '>='
        return ['&', ('rental_state', 'in', ('confirmed', 'active')),
                '&', ('rental_return_date', '!=', False), ('rental_return_date', date_op, today)]

    @api.depends('rental_destination_id', 'rental_vehicle_category_id', 'rental_pickup_date', 'rental_return_date',
                 'rental_daily_rate', 'rental_days')
    def _compute_rental_pricing(self):
        for order in self:
            # Rental-day calculation: inclusive of pickup and return day, minimum one day.
            if order.rental_pickup_date and order.rental_return_date:
                if order.rental_return_date < order.rental_pickup_date:
                    order.rental_days = 0
                else:
                    order.rental_days = (order.rental_return_date - order.rental_pickup_date).days + 1
            elif not order.rental_days:
                order.rental_days = 0.0

            # Destination-based pricing engine - only re-rate open orders so that
            # confirmed orders keep their historical rate snapshot.
            if order.rental_state in ('draft', 'quotation', False):
                rule, daily_rate = self.env['car.rental.pricing.rule'].get_applicable_rate(
                    order.company_id.id,
                    order.rental_vehicle_category_id.id,
                    order.rental_destination_id.id,
                    order.rental_days,
                    order.rental_pickup_date,
                )
                order.pricing_rule_id = rule
                order.rental_daily_rate = daily_rate

            # Deposit policy: one applicable rental day (liability, not revenue).
            category = order.rental_vehicle_category_id
            if category and category.deposit_method != 'none':
                order.security_deposit_amount = order.rental_daily_rate
            else:
                order.security_deposit_amount = 0.0

    @api.depends('deposit_ids.status')
    def _compute_deposit_status(self):
        for order in self:
            deposit = order.deposit_ids[:1]
            order.deposit_status = deposit.status if deposit else 'none'

    def _compute_rental_counts(self):
        for order in self:
            order.inspection_count = len(order.inspection_ids)
            order.damage_count = len(order.damage_ids)
            order.deposit_count = len(order.deposit_ids)
            order.charge_count = len(order.charge_ids)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_rental_manager(self):
        return self.env.user.has_group('car_rental_management.car_rental_group_manager')

    def _ensure_rental_editable(self, fields_changed=None):
        """Block pricing changes on confirmed+ orders by unauthorized users."""
        for order in self:
            if order.rental_state in ('draft', 'quotation', 'cancelled', False):
                continue
            if fields_changed and PRICING_FIELDS & set(fields_changed) and not order._is_rental_manager():
                raise AccessError(_(
                    'Only Rental Managers may change pricing on confirmed rental orders.'))

    def _get_rental_line(self):
        self.ensure_one()
        product = self.rental_vehicle_category_id.rental_product_id
        if not product:
            return self.env['sale.order.line']
        return self.order_line.filtered(lambda line: line.is_rental_line or line.product_id == product)[:1]

    def _sync_rental_line(self):
        """Keep one sale order line priced from the destination-based pricing engine."""
        for order in self:
            if order.rental_state in ('cancelled', 'closed'):
                continue
            product = order.rental_vehicle_category_id.rental_product_id
            if not product:
                raise UserError(_(
                    'The vehicle category "%(category)s" has no rental product configured. '
                    'Set it in Car Rental > Configuration > Vehicle Categories.',
                    category=order.rental_vehicle_category_id.name or ''))
            if order.rental_daily_rate <= 0:
                raise UserError(_(
                    'No applicable pricing rule was found for destination "%(destination)s" and category '
                    '"%(category)s" on %(date)s. Rental orders cannot be confirmed without a rate.',
                    destination=order.rental_destination_id.name or '',
                    category=order.rental_vehicle_category_id.name or '',
                    date=order.rental_pickup_date or _('the pickup date')))
            line = order._get_rental_line()
            description = _(
                '%(category)s Rental - %(vehicle)s to %(destination)s (%(days)s day(s))',
                category=order.rental_vehicle_category_id.name,
                vehicle=order.allocated_vehicle_id.display_name or '',
                destination=order.rental_destination_id.name or '',
                days=order.rental_days)
            if line:
                line.write({
                    'product_id': product.id,
                    'name': description,
                    'product_uom_qty': order.rental_days or 1,
                    'price_unit': order.rental_daily_rate,
                })
            else:
                self.env['sale.order.line'].create({
                    'order_id': order.id,
                    'product_id': product.id,
                    'name': description,
                    'product_uom_qty': order.rental_days or 1,
                    'price_unit': order.rental_daily_rate,
                    'is_rental_line': True,
                })

    def _check_vehicle_availability(self, vehicle, pickup_date, return_date):
        """Prevent overlapping reservations for the same physical vehicle."""
        self.ensure_one()
        if not vehicle or not pickup_date or not return_date:
            return
        overlapping = self.search([
            ('id', '!=', self.id),
            ('allocated_vehicle_id', '=', vehicle.id),
            ('rental_state', 'in', ('confirmed', 'active', 'returned')),
            ('rental_pickup_date', '<=', return_date),
            ('rental_return_date', '>=', pickup_date),
        ], limit=1)
        if overlapping:
            raise UserError(_(
                'Vehicle "%(vehicle)s" is already booked on rental order %(order)s from '
                '%(date_from)s to %(date_to)s. Double booking is not allowed.',
                vehicle=vehicle.display_name, order=overlapping.name,
                date_from=overlapping.rental_pickup_date, date_to=overlapping.rental_return_date))

    def _validate_confirmation(self):
        self.ensure_one()
        if not self.rental_vehicle_category_id:
            raise UserError(_('Select a vehicle category before confirming the rental.'))
        if not self.rental_destination_id:
            raise UserError(_('Select a rental destination before confirming the rental.'))
        if not self.rental_pickup_date or not self.rental_return_date:
            raise UserError(_('Enter the pickup and return dates before confirming the rental.'))
        if self.rental_return_date < self.rental_pickup_date:
            raise UserError(_('The return date cannot be before the pickup date.'))
        if self.rental_days < 1:
            raise UserError(_('The rental duration is invalid (minimum one day).'))
        if not self.pricing_rule_id or self.rental_daily_rate <= 0:
            raise UserError(_(
                'No applicable pricing rule for destination "%(destination)s" / category "%(category)s". '
                'Confirmation is blocked until a valid rate exists.',
                destination=self.rental_destination_id.name,
                category=self.rental_vehicle_category_id.name))
        if self.pricing_override and not self.pricing_override_reason:
            raise UserError(_('A pricing override requires a documented reason.'))
        if self.pricing_override and not self._is_rental_manager():
            raise AccessError(_('Only Rental Managers may apply a pricing override.'))
        if self.rental_destination_id.is_cross_border and not self.cross_border_approved:
            raise UserError(_(
                'Destination "%(destination)s" is a cross-border destination and requires approval '
                'before confirmation.', destination=self.rental_destination_id.name))

    # ------------------------------------------------------------------
    # Workflow actions
    # ------------------------------------------------------------------

    def action_create_quotation(self):
        for order in self:
            if order.rental_state != 'draft':
                continue
            order._validate_confirmation()
            order._sync_rental_line()
            order.rental_state = 'quotation'
            template = self.env.ref('car_rental_management.mail_template_rental_quotation', raise_if_not_found=False)
            if template:
                template.send_mail(order.id, force_send=False)

    def action_allocate_vehicle(self):
        """Allocate a physical vehicle after the commercial rate is established."""
        for order in self:
            if order.rental_state not in ('draft', 'quotation'):
                raise UserError(_('Vehicles can only be allocated before the rental is confirmed.'))
            if not order.allocated_vehicle_id:
                raise UserError(_('Select a vehicle to allocate.'))
            vehicle = order.allocated_vehicle_id
            if order.rental_vehicle_category_id and vehicle.rental_category_id \
                    and vehicle.rental_category_id != order.rental_vehicle_category_id:
                raise UserError(_(
                    'Vehicle "%(vehicle)s" does not belong to category "%(category)s".',
                    vehicle=vehicle.display_name, category=order.rental_vehicle_category_id.name))
            order._check_vehicle_availability(vehicle, order.rental_pickup_date, order.rental_return_date)
            vehicle.message_post(body=_(
                'Allocated to rental order %(order)s (%(date_from)s > %(date_to)s).',
                order=order.name, date_from=order.rental_pickup_date, date_to=order.rental_return_date))

    def action_confirm_rental(self):
        for order in self:
            order._validate_confirmation()
            if not order.allocated_vehicle_id:
                raise UserError(_(
                    'Allocate a vehicle before confirming. Availability is checked and the physical '
                    'vehicle is allocated after the rental price is established.'))
            vehicle = order.allocated_vehicle_id
            if order.rental_vehicle_category_id and vehicle.rental_category_id \
                    and vehicle.rental_category_id != order.rental_vehicle_category_id:
                raise UserError(_(
                    'Vehicle "%(vehicle)s" does not belong to category "%(category)s".',
                    vehicle=vehicle.display_name, category=order.rental_vehicle_category_id.name))
            vehicle._check_rental_availability()
            vehicle._check_handover_readiness(order)
            order._check_vehicle_availability(vehicle, order.rental_pickup_date, order.rental_return_date)
            order._sync_rental_line()
            if order.pricing_override and not order.pricing_override_user_id:
                order.pricing_override_user_id = order.env.user
            if order.pricing_rule_id:
                order.pricing_rule_id.message_post(body=_(
                    'Rate %(rate)s applied on rental order %(order)s.',
                    rate=order.rental_daily_rate, order=order.name))
            # Confirm the underlying sale order.
            if order.state in ('draft', 'sent'):
                super(SaleOrder, order).action_confirm()
            order.rental_state = 'confirmed'
            order.deposit_ids._sync_from_order()
            if not order.deposit_ids:
                deposit_method = order.rental_vehicle_category_id.deposit_method
                self.env['car.rental.deposit'].create({
                    'rental_order_id': order.id,
                    'customer_id': order.partner_id.id,
                    'vehicle_id': vehicle.id,
                    'amount': order.security_deposit_amount,
                    'status': 'not_required' if deposit_method == 'none' else 'required',
                    'company_id': order.company_id.id,
                })
            vehicle.sudo().write({
                'rental_status': 'reserved',
                'current_rental_customer_id': order.partner_id.id,
                'current_rental_order_id': order.id,
                'current_destination_id': order.rental_destination_id.id,
            })

    def action_pickup(self):
        for order in self:
            if order.rental_state != 'confirmed':
                raise UserError(_('Only confirmed rentals can be picked up.'))
            vehicle = order.allocated_vehicle_id
            if not vehicle:
                raise UserError(_('No vehicle is allocated to this rental.'))
            pickup_inspection = order.inspection_ids.filtered(lambda insp: insp.inspection_type == 'pickup' and insp.state == 'done')
            if not pickup_inspection:
                raise UserError(_(
                    'The pickup inspection is mandatory. Complete the pickup inspection before handover.'))
            deposit = order.deposit_ids[:1]
            if deposit and deposit.status not in ('collected', 'partially_applied', 'not_required'):
                if not order._is_rental_manager():
                    raise UserError(_(
                        'The security deposit has not been collected. Handover is blocked until the '
                        'deposit is recorded (a Rental Manager may override).'))
                deposit.message_post(body=_(
                    'Deposit not collected at handover. Override by %(user)s.',
                    user=order.env.user.name))
            vehicle._check_handover_readiness(order)
            order._check_vehicle_availability(vehicle, order.rental_pickup_date, fields.Date.context_today(order))
            order.write({
                'actual_pickup_datetime': fields.Datetime.now(),
                'pickup_mileage': vehicle.current_mileage,
                'rental_state': 'active',
            })
            vehicle.sudo().write({
                'rental_status': 'rented',
                'current_rental_customer_id': order.partner_id.id,
                'current_rental_order_id': order.id,
                'current_destination_id': order.rental_destination_id.id,
            })
            template = self.env.ref('car_rental_management.mail_template_rental_pickup', raise_if_not_found=False)
            if template:
                template.send_mail(order.id, force_send=False)

    def action_return(self):
        for order in self:
            if order.rental_state != 'active':
                raise UserError(_('Only active rentals can be returned.'))
            vehicle = order.allocated_vehicle_id
            now = fields.Datetime.now()
            return_datetime = order.actual_return_datetime or now
            order.write({
                'actual_return_datetime': return_datetime,
                'return_mileage': vehicle.current_mileage,
                'rental_state': 'returned',
            })
            vehicle.sudo().write({'rental_status': 'inspection_pending'})
            order._apply_late_return_charges(return_datetime)
            template = self.env.ref('car_rental_management.mail_template_rental_return', raise_if_not_found=False)
            if template:
                template.send_mail(order.id, force_send=False)

    def _apply_late_return_charges(self, return_datetime):
        """Compare contractual versus actual return and invoke late-charge logic."""
        self.ensure_one()
        if not self.rental_return_date or not return_datetime:
            return
        company = self.company_id
        planned = datetime.combine(self.rental_return_date, datetime.max.time())
        grace = timedelta(hours=company.rental_late_grace_hours or 0)
        late_seconds = (return_datetime - planned).total_seconds() - grace.total_seconds()
        if late_seconds <= 0:
            return
        late_hours = late_seconds / 3600.0
        daily_rate = self.rental_daily_rate or 0.0
        hourly_rate = company.rental_late_hourly_rate or (daily_rate / 24.0 if daily_rate else 0.0)
        threshold = company.rental_late_extra_day_threshold or 24.0
        if late_hours >= threshold:
            late_days = math.ceil((return_datetime - planned).total_seconds() / 86400.0)
            amount = late_days * daily_rate
            quantity, unit_amount = late_days, daily_rate
        else:
            amount = late_hours * hourly_rate
            quantity, unit_amount = round(late_hours, 2), hourly_rate
        if amount <= 0:
            return
        existing = self.charge_ids.filtered(lambda charge: charge.charge_type == 'late_return')
        if existing:
            existing.write({'quantity': quantity, 'unit_amount': unit_amount})
        else:
            self.env['car.rental.charge'].create({
                'rental_order_id': self.id,
                'vehicle_id': self.allocated_vehicle_id.id,
                'charge_type': 'late_return',
                'description': _(
                    'Late return: %(hours).1f hour(s) after the planned return of %(date)s',
                    hours=late_hours, date=self.rental_return_date),
                'quantity': quantity,
                'unit_amount': unit_amount,
                'company_id': self.company_id.id,
            })

    def action_settle(self):
        for order in self:
            if order.rental_state != 'returned':
                raise UserError(_('Only returned rentals awaiting inspection can be settled.'))
            return_inspection = order.inspection_ids.filtered(lambda insp: insp.inspection_type == 'return' and insp.state == 'done')
            if not return_inspection:
                raise UserError(_(
                    'The return inspection is mandatory. Complete it before closing the rental.'))
            pending = order.damage_ids.filtered(lambda damage: damage.approval_status == 'draft')
            if order.damage_ids and pending:
                raise UserError(_(
                    'Damage assessments must be approved or rejected before settlement.'))
            deposit = order.deposit_ids[:1]
            if deposit and deposit.status in ('collected', 'partially_applied'):
                deposit.action_request_refund()
            vehicle = order.allocated_vehicle_id
            approved_damage = order.damage_ids.filtered(lambda damage: damage.approval_status == 'approved')
            if approved_damage:
                vehicle.sudo().write({'rental_status': 'damaged'})
            else:
                vehicle.sudo().write({'rental_status': 'cleaning'})
            order.rental_state = 'settled'
            template = self.env.ref('car_rental_management.mail_template_deposit_settlement', raise_if_not_found=False)
            if template and deposit:
                template.send_mail(deposit.id, force_send=False)

    def action_close(self):
        for order in self:
            if order.rental_state != 'settled':
                raise UserError(_('Settle the rental (return inspection and damage review) before closing it.'))
            order.rental_state = 'closed'
            vehicle = order.allocated_vehicle_id
            if vehicle and vehicle.rental_status in ('cleaning', 'maintenance', 'damaged', 'inspection_pending'):
                vehicle.sudo().write({
                    'rental_status': 'available' if vehicle.rental_status == 'cleaning' else vehicle.rental_status,
                })
            if vehicle and vehicle.current_rental_order_id == order:
                vehicle.sudo().write({
                    'current_rental_customer_id': False,
                    'current_rental_order_id': False,
                    'current_destination_id': False,
                })

    def action_cancel_rental(self):
        for order in self:
            if order.rental_state in ('active', 'returned', 'settled'):
                raise UserError(_('A rental in progress cannot be cancelled. Settle it first.'))
            order.rental_state = 'cancelled'
            if order.state in ('draft', 'sent'):
                order.state = 'cancel'
            deposit = order.deposit_ids[:1]
            if deposit and deposit.status == 'required':
                deposit.unlink()
            vehicle = order.allocated_vehicle_id
            if vehicle and vehicle.current_rental_order_id == order:
                vehicle.sudo().write({
                    'rental_status': 'available',
                    'current_rental_customer_id': False,
                    'current_rental_order_id': False,
                    'current_destination_id': False,
                })

    def action_recalculate_pricing(self):
        """Manual re-rate (draft/quotation only); confirmed orders keep their snapshot."""
        for order in self:
            if order.rental_state not in ('draft', 'quotation', 'cancelled'):
                raise UserError(_(
                    'Confirmed orders retain the rate used at confirmation. Create a new '
                    'quotation to re-price a confirmed rental.'))
            order._compute_rental_pricing()
            order._sync_rental_line()

    def action_view_inspections(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('car_rental_management.action_rental_inspection')
        action['domain'] = [('rental_order_id', '=', self.id)]
        action['context'] = {'default_rental_order_id': self.id}
        return action

    def action_view_damages(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('car_rental_management.action_rental_damage')
        action['domain'] = [('rental_order_id', '=', self.id)]
        action['context'] = {'default_rental_order_id': self.id}
        return action

    def action_view_deposits(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('car_rental_management.action_rental_deposit')
        action['domain'] = [('rental_order_id', '=', self.id)]
        action['context'] = {'default_rental_order_id': self.id}
        return action

    def action_view_charges(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('car_rental_management.action_rental_charge')
        action['domain'] = [('rental_order_id', '=', self.id)]
        action['context'] = {'default_rental_order_id': self.id}
        return action

    # ------------------------------------------------------------------
    # Overrides
    # ------------------------------------------------------------------

    def write(self, vals):
        if PRICING_FIELDS & set(vals):
            for order in self:
                if order.rental_state not in ('draft', 'quotation', 'cancelled', False) \
                        and not order._is_rental_manager():
                    raise AccessError(_(
                        'Only Rental Managers may change pricing on confirmed rental orders.'))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_rental(self):
        for order in self:
            if order.rental_state in ('confirmed', 'active', 'returned', 'settled'):
                raise UserError(_(
                    'Rental order %(order)s is in progress and cannot be deleted.',
                    order=order.name))

    @api.model
    def _cron_rental_overdue(self):
        """Notify about overdue rentals (due time exceeded)."""
        orders = self.search([
            ('rental_state', 'in', ('confirmed', 'active')),
            ('rental_return_date', '!=', False),
            ('rental_return_date', '<', fields.Date.context_today(self)),
        ])
        for order in orders:
            existing = self.env['mail.activity'].search_count([
                ('res_model', '=', self._name),
                ('res_id', '=', order.id),
                ('summary', '=', _('Rental overdue')),
            ])
            if not existing:
                order.activity_schedule(
                    'mail.mail_activity_data_todo',
                    date_deadline=fields.Date.context_today(self),
                    summary=_('Rental overdue'),
                    note=_(
                        'Rental %(order)s was due back on %(date)s and has not been returned.',
                        order=order.name, date=order.rental_return_date),
                )
            template = self.env.ref('car_rental_management.mail_template_rental_overdue', raise_if_not_found=False)
            if template and not order.is_late_return:
                template.send_mail(order.id, force_send=False)


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    is_rental_line = fields.Boolean(string='Rental Line', copy=False)
    rental_destination_id = fields.Many2one(
        'car.rental.destination', related='order_id.rental_destination_id', string='Destination', store=True)
    allocated_vehicle_id = fields.Many2one(
        'fleet.vehicle', related='order_id.allocated_vehicle_id', string='Vehicle', store=True)
