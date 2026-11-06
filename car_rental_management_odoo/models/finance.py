from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.float_utils import float_compare

from .pricing import require_role
from .workflow import window


class Company(models.Model):
    _inherit = 'res.company'

    cr_income_account_id = fields.Many2one('account.account', string='Rental Income Account')
    cr_damage_account_id = fields.Many2one('account.account', string='Damage Recovery Income Account')
    cr_deposit_account_id = fields.Many2one('account.account', string='Customer Deposit Liability Account')
    cr_deposit_pending_account_id = fields.Many2one(
        'account.account', string='Unpaid Deposit Clearing Liability Account')
    cr_expense_account_id = fields.Many2one('account.account', string='Vehicle Maintenance Expense Account')
    cr_cash_journal_id = fields.Many2one('account.journal', string='Deposit / Receipt Bank or Cash Journal')
    cr_sales_journal_id = fields.Many2one('account.journal', string='Rental Sales Journal')
    cr_rental_product_id = fields.Many2one(
        'product.product', string='Rental Service Product',
        default=lambda self: self.env.ref(
            'car_rental_management_odoo.rental_service_product', raise_if_not_found=False))
    cr_deposit_product_id = fields.Many2one(
        'product.product', string='Rental Security Deposit Product',
        default=lambda self: self.env.ref(
            'car_rental_management_odoo.rental_deposit_product', raise_if_not_found=False))
    cr_delivery_product_id = fields.Many2one(
        'product.product', string='Customer Delivery Product',
        default=lambda self: self.env.ref(
            'car_rental_management_odoo.rental_delivery_product', raise_if_not_found=False))
    cr_collection_product_id = fields.Many2one(
        'product.product', string='Off-site Collection Product',
        default=lambda self: self.env.ref(
            'car_rental_management_odoo.rental_collection_product', raise_if_not_found=False))
    cr_cleaning_product_id = fields.Many2one(
        'product.product', string='Dirty-return Cleaning Product',
        default=lambda self: self.env.ref(
            'car_rental_management_odoo.rental_cleaning_product', raise_if_not_found=False))
    cr_late_product_id = fields.Many2one(
        'product.product', string='Late Return Product',
        default=lambda self: self.env.ref(
            'car_rental_management_odoo.rental_late_product', raise_if_not_found=False))
    cr_tax_id = fields.Many2one('account.tax', string='Rental Sales Tax')
    rental_agreement_terms = fields.Text(string='Approved Rental Agreement Terms')
    rental_require_full_payment = fields.Boolean(default=True, string='Require Full Rental Payment Before Pickup')
    rental_block_expired_documents = fields.Boolean(default=False, string='Require Valid Vehicle Compliance Documents')
    rental_block_tracker = fields.Boolean(default=False, string='Require an Operational Tracker')
    rental_late_grace_hours = fields.Float(default=2, string='Late Return Grace (hours)')
    rental_allow_direct_invoice = fields.Boolean(default=False, string='Allow Direct Rental Invoicing Without a Sales Order')

    @api.model
    def _ensure_default_rental_products(self):
        products = {
            'cr_rental_product_id': 'rental_service_product',
            'cr_deposit_product_id': 'rental_deposit_product',
            'cr_delivery_product_id': 'rental_delivery_product',
            'cr_collection_product_id': 'rental_collection_product',
            'cr_cleaning_product_id': 'rental_cleaning_product',
            'cr_late_product_id': 'rental_late_product',
        }
        for company in self.sudo().search([]):
            values = {}
            for field_name, external_id in products.items():
                if not company[field_name]:
                    product = self.env.ref(
                        'car_rental_management_odoo.%s' % external_id,
                        raise_if_not_found=False)
                    if product:
                        values[field_name] = product.id
            if values:
                company.write(values)

    @api.constrains(
        'cr_income_account_id', 'cr_damage_account_id', 'cr_deposit_account_id',
        'cr_deposit_pending_account_id', 'cr_cash_journal_id', 'cr_sales_journal_id',
        'cr_expense_account_id', 'cr_tax_id', 'cr_deposit_product_id',
        'cr_delivery_product_id', 'cr_collection_product_id', 'cr_cleaning_product_id',
        'cr_late_product_id', 'cr_rental_product_id', 'rental_late_grace_hours')
    def _check_rental_configuration(self):
        for company in self:
            for field in ['cr_income_account_id', 'cr_damage_account_id', 'cr_deposit_account_id', 'cr_deposit_pending_account_id', 'cr_expense_account_id']:
                account = company[field]
                if account and company not in account.company_ids:
                    raise ValidationError('Rental accounts must belong to the selected company.')
            if company.cr_deposit_account_id and company.cr_deposit_account_id.account_type != 'liability_current':
                raise ValidationError('Customer security deposits must use a current liability account.')
            if company.cr_deposit_pending_account_id and company.cr_deposit_pending_account_id.account_type != 'liability_current':
                raise ValidationError('Unpaid security deposits must use a current liability clearing account.')
            if (
                company.cr_deposit_account_id
                and company.cr_deposit_pending_account_id == company.cr_deposit_account_id
            ):
                raise ValidationError('Use a separate clearing liability account for invoiced but unpaid deposits.')
            for field in ['cr_income_account_id', 'cr_damage_account_id']:
                if company[field] and company[field].account_type not in ('income', 'income_other'):
                    raise ValidationError('Rental and damage recovery accounts must be income accounts.')
            for field in ['cr_cash_journal_id', 'cr_sales_journal_id']:
                if company[field] and company[field].company_id != company:
                    raise ValidationError('Rental journals must belong to the selected company.')
            if company.cr_cash_journal_id and company.cr_cash_journal_id.type not in ('cash', 'bank'):
                raise ValidationError('Use a bank or cash journal for deposits and receipts.')
            if company.cr_cash_journal_id.currency_id and company.cr_cash_journal_id.currency_id != company.currency_id:
                raise ValidationError('Use a receipt journal in the company currency.')
            if company.cr_sales_journal_id and company.cr_sales_journal_id.type != 'sale':
                raise ValidationError('Rental invoicing requires a sales journal.')
            product_fields = (
                'cr_rental_product_id', 'cr_deposit_product_id', 'cr_delivery_product_id',
                'cr_collection_product_id', 'cr_cleaning_product_id', 'cr_late_product_id')
            for field_name in product_fields:
                product = company[field_name]
                if product and (
                    product.type != 'service'
                    or (product.company_id and product.company_id != company)
                ):
                    raise ValidationError(
                        '%s must be a service product available to %s; got %s (%s, company %s).' % (
                            product.display_name, company.display_name, product.type,
                            product.company_id.display_name or 'shared',
                            product.company_id.id or 'none'))
            if company.cr_deposit_product_id and company.cr_deposit_product_id.taxes_id:
                raise ValidationError('The security deposit product must not have customer taxes.')
            if company.rental_late_grace_hours < 0:
                raise ValidationError('The late return grace period cannot be negative.')


class Settings(models.TransientModel):
    _inherit = 'res.config.settings'

    cr_income_account_id = fields.Many2one(related='company_id.cr_income_account_id', readonly=False)
    cr_damage_account_id = fields.Many2one(related='company_id.cr_damage_account_id', readonly=False)
    cr_deposit_account_id = fields.Many2one(related='company_id.cr_deposit_account_id', readonly=False)
    cr_deposit_pending_account_id = fields.Many2one(
        related='company_id.cr_deposit_pending_account_id', readonly=False)
    cr_expense_account_id = fields.Many2one(related='company_id.cr_expense_account_id', readonly=False)
    cr_cash_journal_id = fields.Many2one(related='company_id.cr_cash_journal_id', readonly=False)
    cr_sales_journal_id = fields.Many2one(related='company_id.cr_sales_journal_id', readonly=False)
    cr_rental_product_id = fields.Many2one(related='company_id.cr_rental_product_id', readonly=False)
    cr_deposit_product_id = fields.Many2one(related='company_id.cr_deposit_product_id', readonly=False)
    cr_delivery_product_id = fields.Many2one(
        related='company_id.cr_delivery_product_id', readonly=False)
    cr_collection_product_id = fields.Many2one(
        related='company_id.cr_collection_product_id', readonly=False)
    cr_cleaning_product_id = fields.Many2one(
        related='company_id.cr_cleaning_product_id', readonly=False)
    cr_late_product_id = fields.Many2one(
        related='company_id.cr_late_product_id', readonly=False)
    cr_tax_id = fields.Many2one(related='company_id.cr_tax_id', readonly=False)
    rental_agreement_terms = fields.Text(related='company_id.rental_agreement_terms', readonly=False)
    rental_require_full_payment = fields.Boolean(related='company_id.rental_require_full_payment', readonly=False)
    rental_block_expired_documents = fields.Boolean(related='company_id.rental_block_expired_documents', readonly=False)
    rental_block_tracker = fields.Boolean(related='company_id.rental_block_tracker', readonly=False)
    rental_late_grace_hours = fields.Float(related='company_id.rental_late_grace_hours', readonly=False)
    rental_allow_direct_invoice = fields.Boolean(related='company_id.rental_allow_direct_invoice', readonly=False)


class Move(models.Model):
    _inherit = 'account.move'

    car_rental_id = fields.Many2one('car.rental.rental', string='Car Rental', ondelete='restrict', copy=False, index=True)
    rental_invoice_kind = fields.Selection([
        ('rental', 'Rental'), ('settlement', 'Final Settlement'),
        ('damage', 'Damage Recovery'), ('late', 'Late Return'),
    ], copy=False)
    rental_deposit_reclass_invoice_id = fields.Many2one(
        'account.move', readonly=True, copy=False, index=True)
    rental_deposit_reclass_type = fields.Selection([
        ('defer', 'Defer Unpaid Deposit'),
        ('recognize', 'Recognize Paid Deposit'),
        ('recognize_reversal', 'Reverse Paid Deposit Recognition'),
        ('defer_reversal', 'Reverse Unpaid Deposit Deferral'),
    ], readonly=True, copy=False)
    rental_deposit_reclass_amount = fields.Monetary(
        currency_field='currency_id', readonly=True, copy=False)

    def _post(self, soft=True):
        for move in self.filtered(lambda m: m.car_rental_id and m.rental_invoice_kind == 'rental' and m.move_type == 'out_invoice'):
            rental = move.car_rental_id
            deposit_lines = move.invoice_line_ids.filtered('rental_deposit_line')
            if deposit_lines:
                hire_total = sum(move.invoice_line_ids.filtered(
                    lambda line: line.display_type == 'product'
                    and not line.rental_deposit_line
                    and not line.rental_charge_kind
                ).mapped('price_total'))
                quote_charge_lines = move.invoice_line_ids.filtered(
                    lambda line: line.rental_charge_kind in ('delivery', 'collection'))
                quote_charge_total = sum(quote_charge_lines.mapped('price_total'))
                expected_quote_charges = rental.reservation_id.quote_service_total
                expected_total = (
                    rental.amount + expected_quote_charges
                    + rental.reservation_id.deposit_required)
                if move.partner_id != rental.partner_id or move.currency_id != rental.currency_id:
                    raise ValidationError('The booking invoice must use the rental customer and currency.')
                if float_compare(
                        hire_total, rental.amount,
                        precision_rounding=move.currency_id.rounding):
                    raise ValidationError('The booking invoice hire lines must equal the approved hire total.')
                if float_compare(
                        quote_charge_total, expected_quote_charges,
                        precision_rounding=move.currency_id.rounding):
                    raise ValidationError('Booking service lines must equal the selected delivery and collection charges.')
                if float_compare(
                        move.amount_total, expected_total,
                        precision_rounding=move.currency_id.rounding):
                    raise ValidationError('The booking invoice total must equal hire, selected services and the required deposit.')
                if any(line.account_id != rental.company_id.cr_deposit_account_id
                       or line.tax_ids for line in deposit_lines):
                    raise ValidationError('Deposit invoice lines must use the configured liability account and have no taxes.')
            elif move.partner_id != rental.partner_id or move.currency_id != rental.currency_id or float_compare(move.amount_total, rental.amount, precision_rounding=move.currency_id.rounding):
                raise ValidationError('A rental invoice must match the agreed booking customer, currency and amount.')
        posted = super()._post(soft=soft)
        for move in posted.filtered(
                lambda record: record.car_rental_id
                and record.rental_invoice_kind == 'rental'
                and record.move_type == 'out_invoice'
                and record.invoice_line_ids.filtered('rental_deposit_line')):
            move.car_rental_id._sync_deposit_liability_reclass(move)
        return posted


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    car_rental_id = fields.Many2one('car.rental.rental', string='Car Rental', ondelete='restrict', copy=False)

    def _validate_rental_quote(self):
        self.ensure_one()
        rental = self.car_rental_id
        if not rental:
            return
        reservation = rental.reservation_id
        currency = rental.currency_id
        if (
            self.partner_id != rental.partner_id
            or self.company_id != rental.company_id
            or self.currency_id != currency
        ):
            raise ValidationError(
                'The rental quotation must use the booking customer, company and currency.')

        product_lines = self.order_line.filtered(lambda line: not line.display_type)
        hire_lines = product_lines.filtered(
            lambda line: not line.rental_deposit_line and not line.rental_charge_kind)
        deposit_lines = product_lines.filtered('rental_deposit_line')
        services = product_lines.filtered(
            lambda line: line.rental_charge_kind in ('delivery', 'collection'))
        if (
            len(hire_lines) != 1
            or len(deposit_lines) != 1
            or len(services) != int(bool(reservation.delivery_service))
                    + int(bool(reservation.collection_service))
            or len(product_lines) != 2 + len(services)
        ):
            raise ValidationError(
                'The rental quotation must contain one hire line, one security deposit '
                'and only the selected booking services.')

        hire = hire_lines
        if (
            hire.product_id != rental.company_id.cr_rental_product_id
            or float_compare(
                hire.product_uom_qty, reservation.number_of_days,
                precision_rounding=hire.product_uom_id.rounding)
            or float_compare(
                hire.price_unit, reservation.quoted_daily_rate,
                precision_rounding=currency.rounding)
            or set(hire.tax_ids.ids) != set(reservation.tax_id.ids)
        ):
            raise ValidationError(
                'The rental quotation hire line must match the approved booking rate, '
                'duration and taxes.')

        deposit = deposit_lines
        if (
            deposit.product_id != rental.company_id.cr_deposit_product_id
            or float_compare(
                deposit.product_uom_qty, 1,
                precision_rounding=deposit.product_uom_id.rounding)
            or float_compare(
                deposit.price_unit, reservation.deposit_required,
                precision_rounding=currency.rounding)
            or deposit.tax_ids
        ):
            raise ValidationError(
                'The rental quotation security deposit must match the booking and have no taxes.')

        expected_services = (
            ('delivery', reservation.delivery_service, reservation.delivery_fee,
             reservation.delivery_address, rental.company_id.cr_delivery_product_id,
             'Customer vehicle delivery'),
            ('collection', reservation.collection_service, reservation.collection_fee,
             reservation.collection_address, rental.company_id.cr_collection_product_id,
             'Off-site vehicle collection'),
        )
        for kind, selected, fee, address, product, label in expected_services:
            lines = services.filtered(lambda line: line.rental_charge_kind == kind)
            if not selected:
                if lines:
                    raise ValidationError(
                        'The rental quotation includes an unselected booking service.')
                continue
            if len(lines) != 1:
                raise ValidationError(
                    'The rental quotation must contain exactly one selected booking service.')
            line = lines
            if (
                line.product_id != product
                or float_compare(
                    line.product_uom_qty, 1,
                    precision_rounding=line.product_uom_id.rounding)
                or float_compare(
                    line.price_unit, fee,
                    precision_rounding=currency.rounding)
                or set(line.tax_ids.ids) != set(reservation.tax_id.ids)
                or line.name != '%s — %s' % (label, address)
            ):
                raise ValidationError(
                    'The rental quotation %s line must match the selected product, '
                    'address, charge and taxes.' % label.lower())

        if float_compare(
                self.amount_total, reservation.quote_total,
                precision_rounding=currency.rounding):
            raise ValidationError(
                'The rental quotation total must equal the approved hire, selected services '
                'and security deposit.')

    def action_confirm(self):
        rental_orders = self.filtered(
            lambda order: order.car_rental_id and order.state in ('draft', 'sent'))
        for order in rental_orders:
            order._validate_rental_quote()
        result = super().action_confirm()
        for order in rental_orders:
            journey = self.env['car.rental.journey'].sudo().search(
                [('reservation_id', '=', order.car_rental_id.reservation_id.id)], limit=1)
            if journey and journey.step == 'quote':
                journey._advance_to('agreement')
        return result

    def action_quotation_send(self):
        for order in self.filtered('car_rental_id'):
            order._validate_rental_quote()
        return super().action_quotation_send()

    def action_cancel(self):
        if self.env.context.get('skip_rental_booking_cancel'):
            return super().action_cancel()
        rental_orders = self.filtered(
            lambda order: order.car_rental_id and order.state in ('draft', 'sent', 'sale'))
        journeys = self.env['car.rental.journey'].sudo()
        for order in rental_orders:
            rental = order.car_rental_id.sudo()
            journey = journeys.search(
                [('reservation_id', '=', rental.reservation_id.id)], limit=1)
            if order.state not in ('draft', 'sent') or not journey or journey.step != 'quote':
                raise ValidationError(
                    'Cancel this rental from its Booking so agreement and accounting '
                    'records remain synchronized.')
            if (
                rental.invoice_ids.filtered(lambda move: move.state != 'cancel')
                or rental.payment_ids
                or rental.deposit_transaction_ids
                or rental.deposit_transfer_in_ids
            ):
                raise ValidationError(
                    'This booking has financial records. Cancel it from Booking with '
                    'Finance so invoices, receipts and deposits are handled safely.')
        result = super().action_cancel()
        for order in rental_orders:
            journey = journeys.search(
                [('reservation_id', '=', order.car_rental_id.reservation_id.id)], limit=1)
            if journey and journey.step != 'cancelled':
                journey.action_cancel()
        return result

    @api.model
    def _cron_cancel_expired_rental_quotes(self):
        expired = self.sudo().search([
            ('car_rental_id', '!=', False),
            ('state', 'in', ('draft', 'sent')),
            ('validity_date', '<', fields.Date.today()),
        ])
        for order in expired:
            rental = order.car_rental_id
            journey = self.env['car.rental.journey'].sudo().search(
                [('reservation_id', '=', rental.reservation_id.id)], limit=1)
            if (
                not journey or journey.step != 'quote' or rental.status != 'draft'
                or rental.invoice_ids.filtered(lambda move: move.state != 'cancel')
                or rental.payment_ids or rental.deposit_transaction_ids
                or rental.deposit_transfer_in_ids
            ):
                continue
            order.action_cancel()
        return True

    def _prepare_invoice(self):
        values = super()._prepare_invoice()
        values['car_rental_id'] = self.car_rental_id.id or False
        if self.car_rental_id:
            self._validate_rental_quote()
            require_role(self.env, 'group_rental_accountant')
            if not self.company_id.cr_sales_journal_id or not self.company_id.cr_income_account_id:
                raise ValidationError('Configure the rental sales journal and income account first.')
            rental = self.car_rental_id
            deposit_lines = self.order_line.filtered('rental_deposit_line')
            hire_total = sum(self.order_line.filtered(
                lambda line: not line.display_type
                and not line.rental_deposit_line
                and not line.rental_charge_kind
            ).mapped('price_total'))
            service_lines = self.order_line.filtered(
                lambda line: line.rental_charge_kind in ('delivery', 'collection'))
            expected_total = (
                rental.amount + rental.reservation_id.quote_service_total
                + rental.reservation_id.deposit_required)
            if deposit_lines and (
                float_compare(
                    hire_total, rental.amount,
                    precision_rounding=self.currency_id.rounding)
                or float_compare(
                    sum(service_lines.mapped('price_total')),
                    rental.reservation_id.quote_service_total,
                    precision_rounding=self.currency_id.rounding)
                or float_compare(
                    sum(deposit_lines.mapped('price_total')),
                    rental.reservation_id.deposit_required,
                    precision_rounding=self.currency_id.rounding)
                or float_compare(
                    self.amount_total, expected_total,
                    precision_rounding=self.currency_id.rounding)
            ):
                raise ValidationError('The booking sales order must equal the approved hire total plus the required deposit.')
            if self.partner_id != rental.partner_id or self.company_id != rental.company_id or self.currency_id != rental.currency_id or float_compare(self.amount_total, expected_total if deposit_lines else rental.amount, precision_rounding=self.currency_id.rounding):
                raise ValidationError('The rental quotation must match the agreed booking amount and currency. Request a pricing override on the booking rather than changing its quotation.')
            if deposit_lines:
                raise ValidationError('Invoice from the booking.')
            values.update({'car_rental_id': self.car_rental_id.id, 'rental_invoice_kind': 'rental', 'journal_id': self.company_id.cr_sales_journal_id.id})
        return values

    def _get_invoice_grouping_keys(self):
        return super()._get_invoice_grouping_keys() + ['car_rental_id']


class SaleLine(models.Model):
    _inherit = 'sale.order.line'

    rental_deposit_line = fields.Boolean(string='Rental Security Deposit', default=False, copy=False)
    rental_charge_kind = fields.Selection([
        ('delivery', 'Customer Delivery'),
        ('collection', 'Vehicle Collection'),
        ('cleaning', 'Dirty-return Cleaning'),
        ('late', 'Late Return'),
    ], copy=False, index=True)

    def _prepare_invoice_line(self, **optional_values):
        values = super()._prepare_invoice_line(**optional_values)
        if self.order_id.car_rental_id and not self.display_type:
            values['rental_deposit_line'] = self.rental_deposit_line
            values['rental_charge_kind'] = self.rental_charge_kind
            values['account_id'] = (
                self.company_id.cr_deposit_account_id.id if self.rental_deposit_line
                else self.company_id.cr_income_account_id.id)
            if self.rental_deposit_line:
                values['tax_ids'] = [fields.Command.clear()]
        return values


class MoveLine(models.Model):
    _inherit = 'account.move.line'

    rental_deposit_line = fields.Boolean(string='Rental Security Deposit', default=False, copy=False)
    rental_charge_kind = fields.Selection([
        ('delivery', 'Customer Delivery'),
        ('collection', 'Vehicle Collection'),
        ('cleaning', 'Dirty-return Cleaning'),
        ('late', 'Late Return'),
    ], string='Rental Charge Type', copy=False, index=True)


class PartialReconcile(models.Model):
    _inherit = 'account.partial.reconcile'

    @api.model_create_multi
    def create(self, vals_list):
        reconciles = super().create(vals_list)
        rentals = reconciles.mapped('debit_move_id.move_id.car_rental_id') | reconciles.mapped(
            'credit_move_id.move_id.car_rental_id')
        rentals._on_invoice_payment_changed()
        return reconciles

    def unlink(self):
        rentals = self.mapped('debit_move_id.move_id.car_rental_id') | self.mapped(
            'credit_move_id.move_id.car_rental_id')
        result = super().unlink()
        rentals._on_invoice_payment_changed()
        return result


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    car_rental_id = fields.Many2one('car.rental.rental', string='Car Rental', ondelete='restrict', copy=False, index=True)
    rental_invoice_kind = fields.Selection([('rental', 'Rental'), ('damage', 'Damage Recovery'), ('late', 'Late Return')], copy=False)
    collection_reference = fields.Char(string='Bank / Receipt Reference', copy=False)
    rental_legacy = fields.Boolean(string='Legacy Receipt', default=False, copy=False, readonly=True)
    rental_refund_of_id = fields.Many2one('account.payment', copy=False, readonly=True)


class Rental(models.Model):
    _inherit = 'car.rental.rental'

    amount = fields.Monetary(related='reservation_id.amount', store=True, readonly=True)
    invoice_ids = fields.One2many('account.move', 'car_rental_id', string='Invoices')
    invoice_count = fields.Integer(compute='_compute_finance', compute_sudo=True)
    financial_balance = fields.Monetary(compute='_compute_finance', compute_sudo=True, string='Total Customer Balance')
    deposit_transaction_ids = fields.One2many('car.rental.deposit.transaction', 'rental_id')
    deposit_transfer_in_ids = fields.One2many('car.rental.deposit.transaction', 'transfer_target_id')
    deposit_held = fields.Monetary(compute='_compute_deposits', string='Deposit Held')
    deposit_collected = fields.Monetary(compute='_compute_deposits')
    deposit_line_total = fields.Monetary(compute='_compute_deposits')
    deposit_paid = fields.Monetary(compute='_compute_deposits')
    deposit_refunded = fields.Monetary(compute='_compute_deposits')
    deposit_retained = fields.Monetary(compute='_compute_deposits')
    deposit_credit_applied = fields.Monetary(compute='_compute_deposits', string='Prior Deposit Credit Applied')
    deposit_transferred_out = fields.Monetary(compute='_compute_deposits', string='Deposit Credit Transferred Out')
    deposit_required = fields.Monetary(related='reservation_id.deposit_required')
    sale_order_id = fields.Many2one('sale.order', string='Sales Quotation', readonly=True, copy=False)
    single_invoice_flow = fields.Boolean(
        compute='_compute_single_invoice_flow', compute_sudo=True)

    @api.depends(
        'sale_order_id.order_line.rental_deposit_line',
        'invoice_ids.rental_invoice_kind',
        'invoice_ids.invoice_line_ids.rental_deposit_line')
    def _compute_single_invoice_flow(self):
        for rental in self:
            rental.single_invoice_flow = rental._uses_single_invoice()

    def _uses_single_invoice(self):
        self.ensure_one()
        return bool(
            self.sale_order_id.order_line.filtered('rental_deposit_line')
            or self.invoice_ids.filtered(
                lambda move: move.rental_invoice_kind == 'rental'
                and move.invoice_line_ids.filtered('rental_deposit_line')))

    def _cancel_single_invoice_booking(self):
        require_role(self.env, 'group_rental_accountant')
        self.ensure_one()
        if self.status != 'draft':
            raise ValidationError('A handed-over rental cannot be cancelled. Return and settle it instead.')
        invoices = self.sudo().invoice_ids.filtered(
            lambda move: move.rental_invoice_kind == 'rental' and move.state != 'cancel')
        if not invoices and not self.sudo().payment_ids and not self.sudo().deposit_transfer_in_ids:
            return
        credit_notes = self.env['account.move']
        refund_amount = 0
        for invoice in invoices:
            if invoice.state == 'draft':
                invoice.button_cancel()
                continue
            if invoice.state != 'posted':
                continue
            credit_transfers = self.sudo().deposit_transfer_in_ids.filtered(
                lambda event: event.kind == 'transfer' and event.state == 'posted'
                and event.charge_invoice_id == invoice and event.account_move_id.state == 'posted'
                and not event.account_move_id.reversal_move_ids.filtered(
                    lambda move: move.state == 'posted'))
            paid_amount = max(
                invoice.amount_total - invoice.amount_residual
                - sum(credit_transfers.mapped('amount')), 0)
            if paid_amount:
                refund_amount += paid_amount
            credit_note = invoice._reverse_moves(
                default_values_list=[{
                    'ref': 'Booking cancelled: %s' % self.reference,
                    'invoice_date': fields.Date.today(),
                }],
            )
            credit_note.action_post()
            (
                invoice.line_ids.filtered(
                    lambda line: line.account_id.account_type == 'asset_receivable')
                + credit_note.line_ids.filtered(
                    lambda line: line.account_id.account_type == 'asset_receivable')
            ).filtered(lambda line: not line.reconciled).reconcile()
            credit_notes |= credit_note
        if refund_amount:
            journal = self.company_id.cr_cash_journal_id
            method_line = journal._get_available_payment_method_lines('outbound')[:1] if journal else False
            if not journal or not method_line:
                raise ValidationError('Configure an outbound payment method on the receiving journal before refunding the cancelled booking.')
            refund = self.env['account.payment'].with_company(self.company_id).create({
                'payment_type': 'outbound',
                'partner_type': 'customer',
                'partner_id': self.partner_id.id,
                'amount': refund_amount,
                'currency_id': self.currency_id.id,
                'date': fields.Date.today(),
                'journal_id': journal.id,
                'payment_method_line_id': method_line.id,
                'destination_account_id': self.partner_id.with_company(self.company_id).property_account_receivable_id.id,
                'payment_reference': 'Cancellation refund: %s' % self.reference,
                'memo': 'Cancellation refund: %s' % self.reference,
                'car_rental_id': self.id,
                'rental_refund_of_id': self.payment_ids[:1].id,
            })
            refund.action_post()
            receivable_lines = credit_notes.line_ids.filtered(
                lambda line: line.account_id.account_type == 'asset_receivable')
            refund_lines = refund.move_id.line_ids.filtered(
                lambda line: line.account_id.account_type == 'asset_receivable')
            (receivable_lines + refund_lines).filtered(
                lambda line: not line.reconciled).reconcile()
        for transfer in self.sudo().deposit_transfer_in_ids.filtered(
                lambda event: event.kind == 'transfer' and event.state == 'posted'
                and event.account_move_id.state == 'posted'):
            reversed_moves = transfer.account_move_id._reverse_moves(
                default_values_list=[{
                    'ref': 'Restore deposit credit for cancelled booking %s' % self.reference,
                    'date': fields.Date.today(),
                }],
            )
            reversed_moves.action_post()
            receivable_lines = (
                credit_notes.line_ids
                + reversed_moves.line_ids
            ).filtered(lambda line: line.account_id.account_type == 'asset_receivable'
                       and not line.reconciled)
            receivable_lines.reconcile()

    @api.depends('invoice_ids.state', 'invoice_ids.amount_residual', 'balance_due')
    def _compute_finance(self):
        for rental in self:
            moves = rental.invoice_ids.filtered(lambda m: m.state == 'posted')
            has_base = bool(moves.filtered(lambda m: m.rental_invoice_kind == 'rental'))
            rental.invoice_count = len(rental.invoice_ids)
            rental.financial_balance = sum(moves.mapped('amount_residual_signed')) + (0 if has_base else rental.balance_due)

    @api.depends(
        'invoice_ids.state', 'invoice_ids.move_type', 'invoice_ids.rental_invoice_kind',
        'invoice_ids.amount_total', 'invoice_ids.amount_residual',
        'invoice_ids.invoice_line_ids.rental_deposit_line',
        'invoice_ids.invoice_line_ids.price_total',
        'deposit_transaction_ids.state', 'deposit_transaction_ids.kind',
        'deposit_transaction_ids.amount', 'deposit_transaction_ids.account_move_id.state',
        'deposit_transaction_ids.account_move_id.reversal_move_ids.state',
        'deposit_transfer_in_ids.state', 'deposit_transfer_in_ids.amount',
        'deposit_transfer_in_ids.account_move_id.state',
        'deposit_transfer_in_ids.account_move_id.reversal_move_ids.state')
    def _compute_deposits(self):
        for rental in self:
            events = rental.deposit_transaction_ids.filtered(lambda d: d.state == 'posted' and d.account_move_id.state == 'posted' and not d.account_move_id.reversal_move_ids.filtered(lambda m: m.state == 'posted'))
            collected = sum(events.filtered(lambda d: d.kind == 'collect').mapped('amount'))
            invoice = rental.invoice_ids.filtered(
                lambda move: move.rental_invoice_kind == 'rental'
                and move.move_type == 'out_invoice' and move.state == 'posted'
                and not move.reversal_move_ids.filtered(lambda reverse: reverse.state == 'posted'))[:1]
            deposit_lines = invoice.invoice_line_ids.filtered('rental_deposit_line')
            deposit_line_total = sum(deposit_lines.mapped('price_total'))
            paid = invoice.amount_total - invoice.amount_residual if invoice else 0
            deposit_paid = min(deposit_line_total, paid) if deposit_lines else 0
            refunded = sum(events.filtered(lambda d: d.kind == 'refund').mapped('amount'))
            retained = sum(events.filtered(lambda d: d.kind == 'retain').mapped('amount'))
            transferred_out = sum(events.filtered(lambda d: d.kind == 'transfer').mapped('amount'))
            transferred_in = sum(rental.deposit_transfer_in_ids.filtered(
                lambda d: d.kind == 'transfer' and d.state == 'posted'
                and d.account_move_id.state == 'posted'
                and not d.account_move_id.reversal_move_ids.filtered(lambda m: m.state == 'posted')
            ).mapped('amount'))
            if deposit_lines:
                transferred_in = 0
            collected_total = deposit_paid + collected
            held = collected_total - refunded - retained - transferred_out
            if not deposit_lines:
                held += transferred_in
            rental.deposit_line_total = deposit_line_total
            rental.deposit_paid = deposit_paid
            rental.deposit_collected = collected_total
            rental.deposit_refunded = refunded
            rental.deposit_retained = retained
            rental.deposit_credit_applied = transferred_in
            rental.deposit_transferred_out = transferred_out
            rental.deposit_held = held

    def _sync_deposit_liability_reclass(self, invoice):
        for rental in self:
            invoice = invoice.filtered(lambda move: move.car_rental_id == rental)
            for move in invoice:
                deposit_lines = move.invoice_line_ids.filtered('rental_deposit_line')
                if move.state != 'posted' or not deposit_lines:
                    continue
                company = rental.company_id
                liability = company.cr_deposit_account_id
                pending = company.cr_deposit_pending_account_id
                journal = company.cr_cash_journal_id
                if not liability or not pending or not journal:
                    raise ValidationError(
                        'Configure the deposit liability account, unpaid-deposit clearing liability account, '
                        'and receiving journal before posting the booking invoice.')
                if liability == pending:
                    raise ValidationError('The deposit clearing account must differ from the deposit liability account.')
                existing = self.env['account.move'].search([
                    ('rental_deposit_reclass_invoice_id', '=', move.id),
                    ('state', '=', 'posted'),
                ])
                deferred_amount = sum(existing.filtered(
                    lambda item: item.rental_deposit_reclass_type == 'defer'
                ).mapped('rental_deposit_reclass_amount'))
                deferred_reversed = sum(existing.filtered(
                    lambda item: item.rental_deposit_reclass_type == 'defer_reversal'
                ).mapped('rental_deposit_reclass_amount'))
                deferred_balance = company.currency_id.round(
                    deferred_amount - deferred_reversed)
                is_reversed = move.state == 'cancel' or bool(
                    move.reversal_move_ids.filtered(lambda reverse: reverse.state == 'posted'))
                if not is_reversed and company.currency_id.is_zero(deferred_amount):
                    deposit_total = sum(deposit_lines.mapped('price_total'))
                    if not company.currency_id.is_zero(deposit_total):
                        _journal_entry(
                            self.env, company, journal,
                            'Defer unpaid deposit: %s' % rental.reference,
                            move.invoice_date or fields.Date.today(),
                            liability, pending, deposit_total, move.partner_id,
                            deposit_invoice=move, reclass_type='defer')
                        deferred_balance = deposit_total
                if is_reversed and company.currency_id.compare_amounts(
                        deferred_balance, 0) > 0:
                    _journal_entry(
                        self.env, company, journal,
                        'Reverse deposit deferral: %s' % rental.reference,
                        fields.Date.today(), pending, liability, deferred_balance,
                        move.partner_id, deposit_invoice=move,
                        reclass_type='defer_reversal')

                recognized = sum(existing.filtered(
                    lambda item: item.rental_deposit_reclass_type == 'recognize'
                ).mapped('rental_deposit_reclass_amount'))
                recognition_reversed = sum(existing.filtered(
                    lambda item: item.rental_deposit_reclass_type == 'recognize_reversal'
                ).mapped('rental_deposit_reclass_amount'))
                recognized_balance = company.currency_id.round(
                    recognized - recognition_reversed)
                paid = max(move.amount_total - move.amount_residual, 0)
                target = 0 if is_reversed else min(
                    sum(deposit_lines.mapped('price_total')), paid)
                delta = company.currency_id.round(target - recognized_balance)
                if company.currency_id.is_zero(delta):
                    continue
                if delta > 0:
                    debit, credit = pending, liability
                    reclass_type = 'recognize'
                    amount = delta
                else:
                    debit, credit = liability, pending
                    reclass_type = 'recognize_reversal'
                    amount = abs(delta)
                _journal_entry(
                    self.env, company, journal,
                    'Recognize paid deposit: %s' % rental.reference,
                    fields.Date.today(), debit, credit, amount, move.partner_id,
                    deposit_invoice=move, reclass_type=reclass_type)

    def _on_invoice_payment_changed(self):
        for rental in self:
            rental.invalidate_recordset(['balance_due', 'deposit_held'])
            for invoice in rental.invoice_ids.filtered(
                    lambda move: move.rental_invoice_kind == 'rental'
                    and move.invoice_line_ids.filtered('rental_deposit_line')):
                rental._sync_deposit_liability_reclass(invoice)
            journey = self.env['car.rental.journey'].sudo().search(
                [('reservation_id', '=', rental.reservation_id.id)], limit=1)
            if (
                journey and journey.step == 'payment' and rental._uses_single_invoice()
                and not rental._journey_payment_blockers()
            ):
                journey._advance_to('pickup')
            settlement = rental.invoice_ids.filtered(
                lambda move: move.rental_invoice_kind == 'settlement'
                and move.state != 'cancel' and move.move_type == 'out_invoice')[:1]
            if (
                rental.status == 'returned' and settlement and settlement.state == 'posted'
                and settlement.currency_id.is_zero(settlement.amount_residual)
            ):
                rental._finish_settlement_if_paid()

    @api.model
    def _deposit_credit_sources(self, partner, company, exclude_rental=None):
        if not partner or not company:
            return self.browse()
        domain = [
            ('partner_id', '=', partner.id), ('company_id', '=', company.id),
            ('status', '=', 'returned'),
        ]
        if exclude_rental:
            domain.append(('id', '!=', exclude_rental.id))
        sources = self.search(domain, order='actual_return_datetime asc, id asc')
        return sources.filtered(
            lambda source: source.return_inspection_done
            and not source._deposit_settlement_pending()
            and company.currency_id.compare_amounts(source.deposit_held, 0) > 0
        )

    def _deposit_settlement_pending(self):
        self.ensure_one()
        unresolved_damage = self.damage_ids.filtered(
            lambda damage: damage.state == 'draft' or (
                damage.cost > 0 and (
                    not damage.invoice_id or damage.invoice_id.state != 'posted'
                    or damage.invoice_id.amount_residual > 0
                )
            )
        )
        unresolved_cleaning = self.invoice_ids.filtered(
            lambda move: move.rental_invoice_kind in ('cleaning', 'damage')
            and move.state != 'cancel'
            and (move.state != 'posted' or move.amount_residual > 0)
        )
        unresolved_settlement = self.invoice_ids.filtered(
            lambda move: move.rental_invoice_kind == 'settlement'
            and move.state != 'cancel'
            and (move.state != 'posted' or not move.currency_id.is_zero(move.amount_residual))
        )
        return bool(unresolved_damage or unresolved_cleaning or unresolved_settlement)

    def _available_deposit_credit(self, partner=None, company=None):
        self.ensure_one()
        sources = self._deposit_credit_sources(
            partner or self.partner_id, company or self.company_id, exclude_rental=self)
        return sum(sources.mapped('deposit_held'))

    def _make_invoice(self, kind, account, lines):
        self.ensure_one()
        require_role(self.env, 'group_rental_accountant')
        self.env.cr.execute('UPDATE car_rental_rental SET id = id WHERE id = %s', [self.id])
        if not account or not self.company_id.cr_sales_journal_id:
            raise ValidationError('Configure rental income accounts and the sales journal in Car Rental Settings first.')
        partner = self.partner_id
        if not partner.with_company(self.company_id).property_account_receivable_id:
            raise ValidationError('Configure the customer receivable account first.')
        invoice_lines = []
        for line in lines:
            line = dict(line)
            line_account = line.pop('account_id', account)
            line_taxes = line.pop('tax_ids', self.reservation_id.tax_id)
            line_sale_ids = line.pop('sale_line_ids', self.env['sale.order.line'])
            invoice_lines.append(fields.Command.create(dict(
                line,
                account_id=line_account.id if line_account else False,
                tax_ids=[fields.Command.set(line_taxes.ids if hasattr(line_taxes, 'ids') else line_taxes)],
                sale_line_ids=[fields.Command.set(line_sale_ids.ids if hasattr(line_sale_ids, 'ids') else line_sale_ids)],
            )))
        return self.env['account.move'].with_company(self.company_id).create({
            'move_type': 'out_invoice', 'partner_id': partner.id, 'company_id': self.company_id.id,
            'journal_id': self.company_id.cr_sales_journal_id.id, 'currency_id': self.currency_id.id,
            'invoice_date': fields.Date.today(), 'invoice_origin': self.reference,
            'car_rental_id': self.id, 'rental_invoice_kind': kind,
            'invoice_line_ids': invoice_lines,
        })

    def action_invoice(self):
        self.ensure_one()
        existing = self.invoice_ids.filtered(lambda m: m.rental_invoice_kind == 'rental' and m.state != 'cancel')[:1]
        if not existing:
            if self._uses_single_invoice() and self.agreement_state != 'signed':
                raise ValidationError('The booking invoice is created after the rental agreement is signed.')
            if self.payment_ids.filtered(lambda p: p.rental_legacy):
                raise ValidationError('This rental has historical unposted receipts. Reconcile its opening balance with your accountant before invoicing to avoid charging twice.')
            if self._uses_single_invoice():
                order = self._ensure_sale_order(include_deposit=True)
                hire_sale_line = order.order_line.filtered(
                    lambda line: not line.display_type
                    and not line.rental_deposit_line
                    and not line.rental_charge_kind)[:1]
                deposit_sale_line = order.order_line.filtered('rental_deposit_line')[:1]
                if not hire_sale_line or not deposit_sale_line:
                    raise ValidationError('The booking sales order must contain separate hire and security-deposit lines.')
                invoice_lines = [{
                    'name': hire_sale_line.name,
                    'quantity': hire_sale_line.product_uom_qty,
                    'price_unit': hire_sale_line.price_unit,
                    'product_id': hire_sale_line.product_id.id,
                    'account_id': self.company_id.cr_income_account_id,
                    'tax_ids': hire_sale_line.tax_ids,
                    'sale_line_ids': hire_sale_line,
                }]
                for sale_line in order.order_line.filtered('rental_charge_kind'):
                    invoice_lines.append({
                        'name': sale_line.name,
                        'quantity': sale_line.product_uom_qty,
                        'price_unit': sale_line.price_unit,
                        'product_id': sale_line.product_id.id,
                        'account_id': self.company_id.cr_income_account_id,
                        'tax_ids': sale_line.tax_ids,
                        'sale_line_ids': sale_line,
                        'rental_charge_kind': sale_line.rental_charge_kind,
                    })
                invoice_lines.append({
                    'name': deposit_sale_line.name,
                    'quantity': deposit_sale_line.product_uom_qty,
                    'price_unit': deposit_sale_line.price_unit,
                    'product_id': deposit_sale_line.product_id.id,
                    'account_id': self.company_id.cr_deposit_account_id,
                    'tax_ids': self.env['account.tax'],
                    'sale_line_ids': deposit_sale_line,
                    'rental_deposit_line': True,
                })
                existing = self._make_invoice(
                    'rental', self.company_id.cr_income_account_id, invoice_lines)
            else:
                if not self.sale_order_id and not self.company_id.rental_allow_direct_invoice:
                    self._ensure_sale_order()
                existing = self._make_invoice('rental', self.company_id.cr_income_account_id, [{
                    'name': '%s — %s — %s days' % (self.reference, self.destination_id.name or 'Rental', self.reservation_id.number_of_days),
                    'quantity': self.reservation_id.number_of_days, 'price_unit': self.reservation_id.quoted_daily_rate,
                    'product_id': self.company_id.cr_rental_product_id.id or False,
                }])
        return window('Rental Invoice', 'account.move', res_id=existing.id)

    def action_late_invoice(self):
        self.ensure_one()
        if self._uses_single_invoice():
            raise ValidationError('Late charges for this booking are included in its final settlement invoice.')
        if self.status != 'returned' or self.late_charge <= 0:
            raise ValidationError('Late return charges are available after completing a late return.')
        invoice = self.invoice_ids.filtered(lambda m: m.rental_invoice_kind == 'late' and m.state != 'cancel')[:1]
        if not invoice:
            invoice = self._make_invoice('late', self.company_id.cr_income_account_id, [{'name': 'Late return: ' + self.reference, 'quantity': self.late_days, 'price_unit': self.reservation_id.quoted_daily_rate}])
        return window('Late Return Invoice', 'account.move', res_id=invoice.id)

    def action_invoices(self):
        self.ensure_one()
        return window('Rental Invoices', 'account.move', [('car_rental_id', '=', self.id)])

    def _prepare_settlement(self):
        self.ensure_one()
        require_role(self.env, 'group_rental_accountant')
        if self.status != 'returned' or not self.return_inspection_done:
            raise ValidationError('Complete the vehicle return and return inspection before settlement.')
        if self.damage_ids.filtered(lambda case: case.state == 'draft'):
            raise ValidationError('Manager approval of damage required before settlement.')
        invoice = self.invoice_ids.filtered(
            lambda move: move.rental_invoice_kind == 'settlement' and move.state != 'cancel')[:1]
        if not invoice:
            charge_lines = []
            if self.late_charge > 0:
                if not self.company_id.cr_late_product_id:
                    raise ValidationError(
                        'Configure the late-return service product in Car Rental Settings.')
                charge_lines.append({
                    'name': 'Late return: %s' % self.reference,
                    'quantity': self.late_days,
                    'price_unit': self.late_unit_price,
                    'product_id': self.company_id.cr_late_product_id.id,
                    'account_id': self.company_id.cr_income_account_id,
                    'tax_ids': self.reservation_id.tax_id,
                    'rental_charge_kind': 'late',
                })
            if self.cleaning_charge > 0:
                if not self.company_id.cr_cleaning_product_id:
                    raise ValidationError(
                        'Configure the dirty-return cleaning product in Car Rental Settings.')
                charge_lines.append({
                    'name': 'Dirty return cleaning: %s' % self.reference,
                    'quantity': 1,
                    'price_unit': self.cleaning_charge,
                    'product_id': self.company_id.cr_cleaning_product_id.id,
                    'account_id': self.company_id.cr_income_account_id,
                    'tax_ids': self.reservation_id.tax_id,
                    'rental_charge_kind': 'cleaning',
                })
            if self.return_collection_service:
                if not self.company_id.cr_collection_product_id:
                    raise ValidationError(
                        'Configure the vehicle collection service product in Car Rental Settings.')
                if not self.return_collection_address or self.return_collection_fee <= 0:
                    raise ValidationError(
                        'Confirm a collection address and positive charge before settlement.')
                charge_lines.append({
                    'name': 'Vehicle collection: %s' % self.return_collection_address,
                    'quantity': 1,
                    'price_unit': self.return_collection_fee,
                    'product_id': self.company_id.cr_collection_product_id.id,
                    'account_id': self.company_id.cr_income_account_id,
                    'tax_ids': self.reservation_id.tax_id,
                    'rental_charge_kind': 'collection',
                })
            for damage in self.damage_ids.filtered(
                    lambda case: case.state != 'draft' and case.cost > 0):
                charge_lines.append({
                    'name': damage.name,
                    'quantity': 1,
                    'price_unit': damage.cost,
                    'product_id': False,
                    'account_id': self.company_id.cr_damage_account_id,
                    'tax_ids': self.reservation_id.tax_id,
                })
            if charge_lines:
                invoice = self._make_invoice(
                    'settlement', self.company_id.cr_income_account_id, charge_lines)
        if invoice and invoice.state == 'draft':
            invoice.action_post()
        if invoice and invoice.state == 'posted':
            for damage in self.damage_ids.filtered(
                    lambda case: case.state != 'draft' and case.cost > 0 and not case.invoice_id):
                self.env.cr.execute(
                    'UPDATE car_rental_damage_case SET invoice_id = %s WHERE id = %s',
                    [invoice.id, damage.id])
                damage.invalidate_recordset(['invoice_id'])
                damage.message_post(body='Included in final settlement invoice %s.' % invoice.display_name)
            existing_retain = self.deposit_transaction_ids.filtered(
                lambda event: event.kind == 'retain'
                and event.charge_invoice_id == invoice)
            retain_amount = min(self.deposit_held, invoice.amount_residual)
            if existing_retain.filtered(lambda event: event.state == 'draft'):
                existing_retain.filtered(lambda event: event.state == 'draft').action_post()
            elif (not existing_retain
                    and self.currency_id.compare_amounts(retain_amount, 0) > 0):
                retain = self.env['car.rental.deposit.transaction'].create({
                    'rental_id': self.id,
                    'kind': 'retain',
                    'amount': retain_amount,
                    'charge_invoice_id': invoice.id,
                })
                retain.action_post()
        return self._finish_settlement_if_paid()

    def _finish_settlement_if_paid(self):
        self.ensure_one()
        invoice = self.invoice_ids.filtered(
            lambda move: move.rental_invoice_kind == 'settlement' and move.state != 'cancel')[:1]
        if invoice and (invoice.state != 'posted' or not invoice.currency_id.is_zero(invoice.amount_residual)):
            return window('Final Settlement Invoice', 'account.move', res_id=invoice.id)
        if self.currency_id.compare_amounts(self.deposit_held, 0) > 0:
            require_role(self.env, 'group_rental_accountant')
            refund = self.env['car.rental.deposit.transaction'].create({
                'rental_id': self.id,
                'kind': 'refund',
                'amount': self.deposit_held,
            })
            refund.action_post()
        journey = self.env['car.rental.journey'].sudo().search(
            [('reservation_id', '=', self.reservation_id.id)], limit=1)
        return journey.action_open() if journey else window('Rental', 'car.rental.rental', res_id=self.id)

    def action_deposits(self):
        self.ensure_one()
        return window('Deposit Transactions', 'car.rental.deposit.transaction', [('rental_id', '=', self.id)], {'default_rental_id': self.id, 'default_amount': max(self.deposit_required - self.deposit_held, 0)})

    def action_collect_deposit(self):
        self.ensure_one()
        return dict(self.action_deposits(), view_mode='form', target='new', context={'default_rental_id': self.id, 'default_kind': 'collect', 'default_amount': max(self.deposit_required - self.deposit_held, 0)})

    def action_refund_deposit(self):
        self.ensure_one()
        return dict(self.action_deposits(), view_mode='form', target='new', context={'default_rental_id': self.id, 'default_kind': 'refund', 'default_amount': self.deposit_held})

    def _ensure_sale_order(self, include_deposit=False):
        self.ensure_one()
        if self.sale_order_id:
            if include_deposit and not self.sale_order_id.order_line.filtered('rental_deposit_line'):
                self._add_deposit_sale_line(self.sale_order_id)
            self._add_quote_service_sale_lines(self.sale_order_id)
            return self.sale_order_id
        if not self.company_id.cr_rental_product_id:
            raise ValidationError('Select the rental service product in Car Rental Settings.')
        if include_deposit and not self.company_id.cr_deposit_product_id:
            raise ValidationError('Select a service product without taxes for rental security deposits in Car Rental Settings.')
        order_lines = [fields.Command.create({
            'product_id': self.company_id.cr_rental_product_id.id, 'name': self.reference,
            'product_uom_qty': self.reservation_id.number_of_days,
            'price_unit': self.reservation_id.quoted_daily_rate,
            'tax_ids': [fields.Command.set(self.reservation_id.tax_id.ids)],
        })]
        order = self.env['sale.order'].with_company(self.company_id).create({
            'partner_id': self.partner_id.id, 'company_id': self.company_id.id,
            'origin': self.reference, 'car_rental_id': self.id, 'order_line': order_lines,
        })
        self.sale_order_id = order
        self._add_quote_service_sale_lines(order)
        if include_deposit:
            self._add_deposit_sale_line(order)
        return order

    def _add_quote_service_sale_lines(self, order):
        self.ensure_one()
        reservation = self.reservation_id
        services = (
            (
                'delivery', reservation.delivery_service, reservation.delivery_fee,
                reservation.delivery_address, self.company_id.cr_delivery_product_id,
                'Customer vehicle delivery',
            ),
            (
                'collection', reservation.collection_service, reservation.collection_fee,
                reservation.collection_address, self.company_id.cr_collection_product_id,
                'Off-site vehicle collection',
            ),
        )
        for kind, selected, amount, address, product, label in services:
            existing = order.order_line.filtered(
                lambda line: line.rental_charge_kind == kind)
            if order.state not in ('draft', 'sent'):
                matches = bool(
                    len(existing) == int(bool(selected))
                    and (
                        not selected
                        or (
                            existing.product_id == product
                            and existing.product_uom_qty == 1
                            and existing.price_unit == amount
                            and existing.name == '%s — %s' % (label, address)
                        )
                    )
                )
                if not matches:
                    raise ValidationError(
                        'The confirmed sales order no longer matches the booking service charges.')
                continue
            if not selected:
                existing.unlink()
                continue
            if not product:
                raise ValidationError(
                    'Configure the %s service product in Car Rental Settings.' % label.lower())
            values = {
                'product_id': product.id,
                'name': '%s — %s' % (label, address),
                'product_uom_qty': 1,
                'price_unit': amount,
                'tax_ids': [fields.Command.set(reservation.tax_id.ids)],
                'rental_charge_kind': kind,
            }
            if existing:
                existing.write(values)
            else:
                order.write({'order_line': [fields.Command.create(values)]})
        return order

    def _add_deposit_sale_line(self, order):
        self.ensure_one()
        product = self.company_id.cr_deposit_product_id
        if not product:
            raise ValidationError('Select a security-deposit service product in Car Rental Settings.')
        if product.type != 'service' or product.taxes_id:
            raise ValidationError('The security-deposit product must be a service product without customer taxes.')
        order.write({'order_line': [fields.Command.create({
            'product_id': product.id,
            'name': 'Refundable security deposit — %s' % self.reference,
            'product_uom_qty': 1,
            'price_unit': self.reservation_id.deposit_required,
            'tax_ids': [fields.Command.clear()],
            'rental_deposit_line': True,
        })]})
        return order

    def action_quotation(self):
        require_role(self.env, 'group_rental_manager')
        self.ensure_one()
        if self.invoice_ids.filtered(lambda m: m.rental_invoice_kind == 'rental' and m.state != 'cancel'):
            raise ValidationError('This rental is already invoiced. Open its invoice instead of creating another commercial document.')
        order = self._ensure_sale_order()
        return window('Rental Quotation', 'sale.order', res_id=order.id)


def _journal_entry(
        env, company, journal, reference, date, debit_account, credit_account,
        amount, partner, deposit_invoice=None, reclass_type=None):
    if not debit_account or not credit_account or amount <= 0:
        raise ValidationError('Posting requires valid accounts and a positive amount.')
    move = env['account.move'].with_company(company).create({
        'move_type': 'entry', 'journal_id': journal.id, 'company_id': company.id,
        'date': date, 'ref': reference,
        'rental_deposit_reclass_invoice_id': deposit_invoice.id if deposit_invoice else False,
        'rental_deposit_reclass_type': reclass_type or False,
        'rental_deposit_reclass_amount': amount if reclass_type else 0,
        'line_ids': [fields.Command.create({'name': reference, 'partner_id': partner.id, 'account_id': debit_account.id, 'debit': amount, 'credit': 0, 'date_maturity': date if debit_account.account_type in ('asset_receivable', 'liability_payable') else False}),
                     fields.Command.create({'name': reference, 'partner_id': partner.id, 'account_id': credit_account.id, 'debit': 0, 'credit': amount, 'date_maturity': date if credit_account.account_type in ('asset_receivable', 'liability_payable') else False})],
    })
    move.action_post()
    return move


class Deposit(models.Model):
    _name = 'car.rental.deposit.transaction'
    _description = 'Rental Security Deposit Transaction'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'rental_id'
    _order = 'date desc, id desc'

    rental_id = fields.Many2one('car.rental.rental', required=True, ondelete='restrict')
    company_id = fields.Many2one(related='rental_id.company_id', store=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    kind = fields.Selection([
        ('collect', 'Collect Deposit'), ('refund', 'Refund Deposit'),
        ('retain', 'Apply to Damage Invoice'), ('transfer', 'Transfer to Another Rental'),
    ], required=True, default='collect')
    amount = fields.Monetary(required=True)
    date = fields.Date(default=fields.Date.today, required=True)
    damage_id = fields.Many2one('car.rental.damage.case')
    transfer_target_id = fields.Many2one(
        'car.rental.rental', string='New Rental', check_company=True, ondelete='restrict')
    account_move_id = fields.Many2one('account.move', readonly=True, copy=False)
    state = fields.Selection([('draft', 'Draft'), ('posted', 'Posted')], default='draft', readonly=True, tracking=True)

    def action_post(self):
        require_role(self.env, 'group_rental_accountant')
        for event in self:
            if event.state != 'draft' or event.amount <= 0:
                raise ValidationError('Post a draft transaction with a positive amount.')
            if event.company_id.currency_id.compare_amounts(
                event.amount, event.company_id.currency_id.round(event.amount)
            ) != 0:
                raise ValidationError('Use the company currency rounding for the deposit amount.')
            self.env.cr.execute('UPDATE car_rental_rental SET id = id WHERE id = %s', [event.rental_id.id])
            event.rental_id.deposit_transaction_ids.invalidate_recordset(['state', 'amount', 'kind'])
            event.rental_id._compute_deposits()
            rental = event.rental_id
            journal = event.company_id.cr_cash_journal_id
            liability = event.company_id.cr_deposit_account_id
            if not journal or not journal.default_account_id or not liability:
                raise ValidationError('Configure the deposit liability account and bank/cash journal first.')
            partner = rental.partner_id
            bank = journal.default_account_id
            debit, credit = bank, liability
            if event.kind == 'collect':
                if rental.status != 'draft' or event.amount > rental.deposit_required - rental.deposit_held + 0.005:
                    raise ValidationError('Collect deposits before pickup, up to the required deposit amount.')
            elif event.kind == 'transfer':
                target = event.transfer_target_id
                if (
                    not target or target == rental or rental.status != 'returned'
                    or not rental.return_inspection_done or rental._deposit_settlement_pending()
                    or target.company_id != rental.company_id or target.partner_id != partner
                    or target.status != 'draft' or target.reservation_id.status != 'confirmed'
                    or event.amount > rental.deposit_held + 0.005
                ):
                    raise ValidationError('Only settled, refundable deposit credit for the same customer and company can be transferred to a confirmed rental.')
                target._compute_deposits()
                if event.amount > target.deposit_required - target.deposit_held + 0.005:
                    raise ValidationError('The transferred credit exceeds the new rental deposit balance.')
                charge_invoice = event.charge_invoice_id
                if target._uses_single_invoice():
                    if (
                        not charge_invoice or charge_invoice.car_rental_id != target
                        or charge_invoice.rental_invoice_kind != 'rental'
                        or charge_invoice.state != 'posted'
                    ):
                        raise ValidationError('Apply prior deposit credit against the new booking invoice.')
                    receivable = charge_invoice.line_ids.filtered(
                        lambda line: line.account_id.account_type == 'asset_receivable')[:1]
                    if not receivable:
                        raise ValidationError('The new booking invoice has no receivable line for deposit credit.')
                    debit, credit = liability, receivable.account_id
                else:
                    debit, credit = liability, liability
            else:
                if rental.status != 'returned' or not rental.return_inspection_done or event.amount > rental.deposit_held + 0.005:
                    raise ValidationError('Settlement requires a returned and inspected rental, and cannot exceed the deposit held.')
                if event.kind == 'refund':
                    if rental._deposit_settlement_pending():
                        raise ValidationError('Settle damage and cleaning charges before refunding the remaining deposit.')
                    debit, credit = liability, bank
                else:
                    damage = event.damage_id
                    charge_invoice = damage.invoice_id if damage else event.charge_invoice_id
                    if damage and (damage.rental_id != rental or damage.state == 'draft'):
                        raise ValidationError('Choose an approved damage case for this rental.')
                    if (not charge_invoice or charge_invoice.state != 'posted'
                            or charge_invoice.car_rental_id != rental
                            or charge_invoice.move_type != 'out_invoice'
                            or (not damage and charge_invoice.rental_invoice_kind not in ('cleaning', 'settlement', 'damage'))):
                        raise ValidationError('Choose a posted damage or cleaning invoice for this rental.')
                    if event.amount > charge_invoice.amount_residual + 0.005:
                        raise ValidationError('Deposit application cannot exceed the charge invoice balance.')
                    debit = liability
                    credit = charge_invoice.line_ids.filtered(lambda l: l.account_id.account_type == 'asset_receivable')[:1].account_id
            move = _journal_entry(event.env, event.company_id, journal, '%s: %s' % (rental.reference, event.kind), event.date, debit, credit, event.amount, partner)
            super(Deposit, event).write({'state': 'posted', 'account_move_id': move.id})
            if event.kind == 'retain' or (
                    event.kind == 'transfer' and event.transfer_target_id._uses_single_invoice()):
                lines = charge_invoice.line_ids.filtered(lambda l: l.account_id == credit)
                (lines + move.line_ids.filtered(lambda l: l.account_id == credit)).reconcile()

    @api.model_create_multi
    def create(self, vals_list):
        if any(v.get('state', 'draft') != 'draft' or v.get('account_move_id') for v in vals_list):
            raise ValidationError('Create a draft deposit transaction first.')
        return super().create(vals_list)

    @api.constrains('kind', 'rental_id', 'transfer_target_id')
    def _check_transfer_target(self):
        for event in self:
            if event.kind == 'transfer':
                if not event.transfer_target_id or event.transfer_target_id == event.rental_id:
                    raise ValidationError('Choose a different target rental for a deposit credit transfer.')
            elif event.transfer_target_id:
                raise ValidationError('Only deposit credit transfers can have a target rental.')

    def write(self, vals):
        if {'state', 'account_move_id'}.intersection(vals) or any(d.state == 'posted' for d in self) and set(vals) - {'message_follower_ids'}:
            raise ValidationError('Posted deposit transactions cannot be changed.')
        return super().write(vals)

    def unlink(self):
        if any(d.state == 'posted' for d in self):
            raise ValidationError('Posted deposit transactions cannot be deleted.')
        return super().unlink()


class Damage(models.Model):
    _inherit = 'car.rental.damage.case'

    def action_invoice(self):
        self.ensure_one()
        if self.rental_id._uses_single_invoice():
            raise ValidationError('Damage charges for this booking are included in its final settlement invoice.')
        if self.state == 'draft' or self.cost <= 0:
            raise ValidationError('Approve a positive damage charge before generating its invoice.')
        if not self.invoice_id:
            invoice = self.rental_id._make_invoice('damage', self.company_id.cr_damage_account_id, [{'name': self.name, 'quantity': 1, 'price_unit': self.cost}])
            # Internal action updates the audited link; direct edits remain blocked.
            self.env.cr.execute('UPDATE car_rental_damage_case SET invoice_id = %s WHERE id = %s', [invoice.id, self.id])
            self.invalidate_recordset(['invoice_id'])
            self.message_post(body='Damage invoice generated: %s.' % invoice.display_name)
        return window('Damage Invoice', 'account.move', res_id=self.invoice_id.id)

    def action_retain_deposit(self):
        self.ensure_one()
        amount = min(self.rental_id.deposit_held, self.invoice_id.amount_residual if self.invoice_id else self.cost)
        return dict(window('Apply Deposit', 'car.rental.deposit.transaction', context={'default_rental_id': self.rental_id.id, 'default_damage_id': self.id, 'default_kind': 'retain', 'default_amount': amount}), view_mode='form', target='new')


class Maintenance(models.Model):
    _inherit = 'maintenance.request'

    def action_rental_bill(self):
        require_role(self.env, 'group_rental_accountant')
        self.ensure_one()
        if not self.rental_vehicle_id or not self.rental_supplier_id or self.rental_cost <= 0 or not self.company_id.cr_expense_account_id:
            raise ValidationError('Select the vehicle, supplier, cost and maintenance expense account first.')
        if not self.rental_bill_id:
            self.rental_bill_id = self.env['account.move'].with_company(self.company_id).create({
                'move_type': 'in_invoice', 'partner_id': self.rental_supplier_id.id, 'company_id': self.company_id.id,
                'invoice_date': fields.Date.today(), 'ref': self.name,
                'invoice_line_ids': [fields.Command.create({'name': self.rental_work or self.name, 'quantity': 1, 'price_unit': self.rental_cost, 'account_id': self.company_id.cr_expense_account_id.id})],
            })
        return window('Maintenance Supplier Bill', 'account.move', res_id=self.rental_bill_id.id)
