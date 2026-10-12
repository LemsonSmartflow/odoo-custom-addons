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
    cr_expense_account_id = fields.Many2one('account.account', string='Vehicle Maintenance Expense Account')
    cr_cash_journal_id = fields.Many2one('account.journal', string='Deposit / Receipt Bank or Cash Journal')
    cr_sales_journal_id = fields.Many2one('account.journal', string='Rental Sales Journal')
    cr_rental_product_id = fields.Many2one('product.product', string='Rental Service Product')
    cr_tax_id = fields.Many2one('account.tax', string='Rental Sales Tax')
    rental_agreement_terms = fields.Text(string='Approved Rental Agreement Terms')
    rental_require_full_payment = fields.Boolean(default=True, string='Require Full Rental Payment Before Pickup')
    rental_block_expired_documents = fields.Boolean(default=True, string='Require Valid Vehicle Compliance Documents')
    rental_block_tracker = fields.Boolean(default=False, string='Require an Operational Tracker')
    rental_late_grace_hours = fields.Float(default=2, string='Late Return Grace (hours)')

    @api.constrains('cr_income_account_id', 'cr_damage_account_id', 'cr_deposit_account_id', 'cr_cash_journal_id', 'cr_sales_journal_id', 'cr_expense_account_id', 'cr_tax_id', 'rental_late_grace_hours')
    def _check_rental_configuration(self):
        for company in self:
            for field in ['cr_income_account_id', 'cr_damage_account_id', 'cr_deposit_account_id', 'cr_expense_account_id']:
                account = company[field]
                if account and company not in account.company_ids:
                    raise ValidationError('Rental accounts must belong to the selected company.')
            if company.cr_deposit_account_id and company.cr_deposit_account_id.account_type != 'liability_current':
                raise ValidationError('Customer security deposits must use a current liability account.')
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
            if company.rental_late_grace_hours < 0:
                raise ValidationError('The late return grace period cannot be negative.')


class Settings(models.TransientModel):
    _inherit = 'res.config.settings'

    cr_income_account_id = fields.Many2one(related='company_id.cr_income_account_id', readonly=False)
    cr_damage_account_id = fields.Many2one(related='company_id.cr_damage_account_id', readonly=False)
    cr_deposit_account_id = fields.Many2one(related='company_id.cr_deposit_account_id', readonly=False)
    cr_expense_account_id = fields.Many2one(related='company_id.cr_expense_account_id', readonly=False)
    cr_cash_journal_id = fields.Many2one(related='company_id.cr_cash_journal_id', readonly=False)
    cr_sales_journal_id = fields.Many2one(related='company_id.cr_sales_journal_id', readonly=False)
    cr_rental_product_id = fields.Many2one(related='company_id.cr_rental_product_id', readonly=False)
    cr_tax_id = fields.Many2one(related='company_id.cr_tax_id', readonly=False)
    rental_agreement_terms = fields.Text(related='company_id.rental_agreement_terms', readonly=False)
    rental_require_full_payment = fields.Boolean(related='company_id.rental_require_full_payment', readonly=False)
    rental_block_expired_documents = fields.Boolean(related='company_id.rental_block_expired_documents', readonly=False)
    rental_block_tracker = fields.Boolean(related='company_id.rental_block_tracker', readonly=False)
    rental_late_grace_hours = fields.Float(related='company_id.rental_late_grace_hours', readonly=False)


class Move(models.Model):
    _inherit = 'account.move'

    car_rental_id = fields.Many2one('car.rental.rental', string='Car Rental', ondelete='restrict', copy=False, index=True)
    rental_invoice_kind = fields.Selection([('rental', 'Rental'), ('damage', 'Damage Recovery'), ('late', 'Late Return')], copy=False)

    def _post(self, soft=True):
        for move in self.filtered(lambda m: m.car_rental_id and m.rental_invoice_kind == 'rental' and m.move_type == 'out_invoice'):
            rental = move.car_rental_id
            if move.partner_id != rental.customer_id.partner_id or move.currency_id != rental.currency_id or float_compare(move.amount_total, rental.amount, precision_rounding=move.currency_id.rounding):
                raise ValidationError('A rental invoice must match the agreed booking customer, currency and amount.')
        return super()._post(soft=soft)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    car_rental_id = fields.Many2one('car.rental.rental', string='Car Rental', ondelete='restrict', copy=False)

    def _prepare_invoice(self):
        values = super()._prepare_invoice()
        values['car_rental_id'] = self.car_rental_id.id or False
        if self.car_rental_id:
            require_role(self.env, 'group_rental_accountant')
            if not self.company_id.cr_sales_journal_id or not self.company_id.cr_income_account_id:
                raise ValidationError('Configure the rental sales journal and income account first.')
            if self.partner_id != self.car_rental_id.customer_id.partner_id or self.company_id != self.car_rental_id.company_id or self.currency_id != self.car_rental_id.currency_id or float_compare(self.amount_total, self.car_rental_id.amount, precision_rounding=self.currency_id.rounding):
                raise ValidationError('The rental quotation must match the agreed booking amount and currency. Request a pricing override on the booking rather than changing its quotation.')
            values.update({'car_rental_id': self.car_rental_id.id, 'rental_invoice_kind': 'rental', 'journal_id': self.company_id.cr_sales_journal_id.id})
        return values

    def _get_invoice_grouping_keys(self):
        return super()._get_invoice_grouping_keys() + ['car_rental_id']


class SaleLine(models.Model):
    _inherit = 'sale.order.line'

    def _prepare_invoice_line(self, **optional_values):
        values = super()._prepare_invoice_line(**optional_values)
        if self.order_id.car_rental_id and not self.display_type:
            values['account_id'] = self.company_id.cr_income_account_id.id
        return values


class Rental(models.Model):
    _inherit = 'car.rental.rental'

    invoice_ids = fields.One2many('account.move', 'car_rental_id', string='Invoices')
    invoice_count = fields.Integer(compute='_compute_finance', compute_sudo=True)
    financial_balance = fields.Monetary(compute='_compute_finance', compute_sudo=True, string='Total Customer Balance')
    deposit_transaction_ids = fields.One2many('car.rental.deposit.transaction', 'rental_id')
    deposit_held = fields.Monetary(compute='_compute_deposits', string='Deposit Held')
    deposit_collected = fields.Monetary(compute='_compute_deposits')
    deposit_refunded = fields.Monetary(compute='_compute_deposits')
    deposit_retained = fields.Monetary(compute='_compute_deposits')
    deposit_required = fields.Monetary(related='reservation_id.deposit_required')
    sale_order_id = fields.Many2one('sale.order', string='Sales Quotation', readonly=True, copy=False)

    @api.depends('invoice_ids.state', 'invoice_ids.amount_residual', 'balance_due')
    def _compute_finance(self):
        for rental in self:
            moves = rental.invoice_ids.filtered(lambda m: m.state == 'posted')
            has_base = bool(moves.filtered(lambda m: m.rental_invoice_kind == 'rental'))
            rental.invoice_count = len(rental.invoice_ids)
            rental.financial_balance = sum(moves.mapped('amount_residual_signed')) + (0 if has_base else rental.balance_due)

    @api.depends('deposit_transaction_ids.state', 'deposit_transaction_ids.kind', 'deposit_transaction_ids.amount', 'deposit_transaction_ids.account_move_id.state', 'deposit_transaction_ids.account_move_id.reversal_move_ids.state')
    def _compute_deposits(self):
        for rental in self:
            events = rental.deposit_transaction_ids.filtered(lambda d: d.state == 'posted' and d.account_move_id.state == 'posted' and not d.account_move_id.reversal_move_ids.filtered(lambda m: m.state == 'posted'))
            collected = sum(events.filtered(lambda d: d.kind == 'collect').mapped('amount'))
            refunded = sum(events.filtered(lambda d: d.kind == 'refund').mapped('amount'))
            retained = sum(events.filtered(lambda d: d.kind == 'retain').mapped('amount'))
            rental.deposit_collected = collected
            rental.deposit_refunded = refunded
            rental.deposit_retained = retained
            rental.deposit_held = collected - refunded - retained

    def _make_invoice(self, kind, account, lines):
        self.ensure_one()
        require_role(self.env, 'group_rental_accountant')
        self.env.cr.execute('UPDATE car_rental_rental SET id = id WHERE id = %s', [self.id])
        if not account or not self.company_id.cr_sales_journal_id:
            raise ValidationError('Configure rental income accounts and the sales journal in Car Rental Settings first.')
        partner = self.customer_id._ensure_partner()
        if not partner.with_company(self.company_id).property_account_receivable_id:
            raise ValidationError('Configure the customer receivable account first.')
        if kind == 'rental' and self.sale_order_id:
            for line in lines:
                line['sale_line_ids'] = [fields.Command.set(self.sale_order_id.order_line.filtered(lambda l: not l.display_type).ids)]
        return self.env['account.move'].with_company(self.company_id).create({
            'move_type': 'out_invoice', 'partner_id': partner.id, 'company_id': self.company_id.id,
            'journal_id': self.company_id.cr_sales_journal_id.id, 'currency_id': self.currency_id.id,
            'invoice_date': fields.Date.today(), 'invoice_origin': self.reference,
            'car_rental_id': self.id, 'rental_invoice_kind': kind,
            'invoice_line_ids': [fields.Command.create(dict(line, account_id=account.id, tax_ids=[fields.Command.set(self.reservation_id.tax_id.ids)])) for line in lines],
        })

    def action_invoice(self):
        self.ensure_one()
        existing = self.invoice_ids.filtered(lambda m: m.rental_invoice_kind == 'rental' and m.state != 'cancel')[:1]
        if not existing:
            if self.payment_ids.filtered(lambda p: p.ledger_state == 'legacy'):
                raise ValidationError('This rental has historical unposted receipts. Reconcile its opening balance with your accountant before invoicing to avoid charging twice.')
            existing = self._make_invoice('rental', self.company_id.cr_income_account_id, [{
                'name': '%s — %s — %s days' % (self.reference, self.destination_id.name or 'Rental', self.reservation_id.number_of_days),
                'quantity': self.reservation_id.number_of_days, 'price_unit': self.reservation_id.quoted_daily_rate,
                'product_id': self.company_id.cr_rental_product_id.id or False,
            }])
        return window('Rental Invoice', 'account.move', res_id=existing.id)

    def action_late_invoice(self):
        self.ensure_one()
        if self.status != 'returned' or self.late_charge <= 0:
            raise ValidationError('Late return charges are available after completing a late return.')
        invoice = self.invoice_ids.filtered(lambda m: m.rental_invoice_kind == 'late' and m.state != 'cancel')[:1]
        if not invoice:
            invoice = self._make_invoice('late', self.company_id.cr_income_account_id, [{'name': 'Late return: ' + self.reference, 'quantity': self.late_days, 'price_unit': self.reservation_id.quoted_daily_rate}])
        return window('Late Return Invoice', 'account.move', res_id=invoice.id)

    def action_invoices(self):
        self.ensure_one()
        return window('Rental Invoices', 'account.move', [('car_rental_id', '=', self.id)])

    def action_deposits(self):
        self.ensure_one()
        return window('Deposit Transactions', 'car.rental.deposit.transaction', [('rental_id', '=', self.id)], {'default_rental_id': self.id, 'default_amount': max(self.deposit_required - self.deposit_collected, 0)})

    def action_collect_deposit(self):
        self.ensure_one()
        return dict(self.action_deposits(), view_mode='form', target='new', context={'default_rental_id': self.id, 'default_kind': 'collect', 'default_amount': max(self.deposit_required - self.deposit_collected, 0)})

    def action_refund_deposit(self):
        self.ensure_one()
        return dict(self.action_deposits(), view_mode='form', target='new', context={'default_rental_id': self.id, 'default_kind': 'refund', 'default_amount': self.deposit_held})

    def action_quotation(self):
        require_role(self.env, 'group_rental_manager')
        self.ensure_one()
        if not self.company_id.cr_rental_product_id:
            raise ValidationError('Select the rental service product in Car Rental Settings.')
        if not self.sale_order_id:
            if self.invoice_ids.filtered(lambda m: m.rental_invoice_kind == 'rental' and m.state != 'cancel'):
                raise ValidationError('This rental is already invoiced. Open its invoice instead of creating another commercial document.')
            order = self.env['sale.order'].with_company(self.company_id).create({
                'partner_id': self.customer_id._ensure_partner().id, 'company_id': self.company_id.id,
                'origin': self.reference, 'car_rental_id': self.id, 'order_line': [fields.Command.create({
                    'product_id': self.company_id.cr_rental_product_id.id, 'name': self.reference,
                    'product_uom_qty': self.reservation_id.number_of_days, 'price_unit': self.reservation_id.quoted_daily_rate,
                    'tax_ids': [fields.Command.set(self.reservation_id.tax_id.ids)],
                })],
            })
            self.sale_order_id = order
        return window('Rental Quotation', 'sale.order', res_id=self.sale_order_id.id)


class Payment(models.Model):
    _name = 'car.rental.payment'
    _inherit = ['car.rental.payment', 'mail.thread', 'mail.activity.mixin']

    company_id = fields.Many2one(related='rental_id.company_id', store=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    ledger_state = fields.Selection([('draft', 'Draft Receipt'), ('posted', 'Posted Receipt'), ('legacy', 'Historical / Unposted')], default='draft', readonly=True, tracking=True, copy=False)
    account_move_id = fields.Many2one('account.move', readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        if any(v.get('ledger_state', 'draft') != 'draft' or v.get('account_move_id') for v in vals_list):
            raise ValidationError('Create draft receipts and post them using Post Receipt.')
        return super().create(vals_list)

    def write(self, vals):
        if {'ledger_state', 'account_move_id'}.intersection(vals) or any(p.ledger_state in ('posted', 'legacy') for p in self) and set(vals) - {'message_follower_ids'}:
            raise ValidationError('Posted and historical receipts cannot be changed. Use accounting reversals for corrections.')
        return super().write(vals)

    def unlink(self):
        if any(p.ledger_state != 'draft' for p in self):
            raise ValidationError('Posted and historical receipts cannot be deleted.')
        return super().unlink()

    def action_post_receipt(self):
        require_role(self.env, 'group_rental_accountant')
        for receipt in self:
            if receipt.ledger_state != 'draft':
                raise ValidationError('Only draft receipts can be posted.')
            invoice = receipt.rental_id.invoice_ids.filtered(lambda m: m.rental_invoice_kind == 'rental' and m.state == 'posted')[:1]
            if not invoice:
                raise ValidationError('Create and post the rental invoice before posting its receipt.')
            self.env.cr.execute('UPDATE car_rental_rental SET id = id WHERE id = %s', [receipt.rental_id.id])
            invoice.invalidate_recordset(['amount_residual'])
            if float_compare(receipt.paid_amount, invoice.amount_residual, precision_rounding=receipt.currency_id.rounding) > 0:
                raise ValidationError('The receipt exceeds the posted invoice balance.')
            journal = receipt.company_id.cr_cash_journal_id
            if not journal or not journal.default_account_id:
                raise ValidationError('Configure a bank/cash journal with its bank/cash account first.')
            receivable_lines = invoice.line_ids.filtered(lambda l: l.account_id.account_type == 'asset_receivable')
            move = _journal_entry(receipt.env, receipt.company_id, journal, receipt.reference, receipt.payment_date,
                                  journal.default_account_id, receivable_lines[:1].account_id,
                                  receipt.paid_amount, invoice.partner_id)
            super(Payment, receipt).write({'ledger_state': 'posted', 'account_move_id': move.id})
            (receivable_lines + move.line_ids.filtered(lambda l: l.account_id == receivable_lines[:1].account_id)).reconcile()
            receipt.message_post(body='Receipt posted to Accounting: %s.' % move.name)

    def action_account_move(self):
        self.ensure_one()
        return window('Receipt Journal Entry', 'account.move', res_id=self.account_move_id.id)


def _journal_entry(env, company, journal, reference, date, debit_account, credit_account, amount, partner):
    if not debit_account or not credit_account or amount <= 0:
        raise ValidationError('Posting requires valid accounts and a positive amount.')
    move = env['account.move'].with_company(company).create({
        'move_type': 'entry', 'journal_id': journal.id, 'company_id': company.id,
        'date': date, 'ref': reference,
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

    rental_id = fields.Many2one('car.rental.rental', required=True, ondelete='restrict')
    company_id = fields.Many2one(related='rental_id.company_id', store=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    kind = fields.Selection([('collect', 'Collect Deposit'), ('refund', 'Refund Deposit'), ('retain', 'Apply to Damage Invoice')], required=True, default='collect')
    amount = fields.Monetary(required=True)
    date = fields.Date(default=fields.Date.today, required=True)
    damage_id = fields.Many2one('car.rental.damage.case')
    account_move_id = fields.Many2one('account.move', readonly=True, copy=False)
    state = fields.Selection([('draft', 'Draft'), ('posted', 'Posted')], default='draft', readonly=True, tracking=True)

    def action_post(self):
        require_role(self.env, 'group_rental_accountant')
        for event in self:
            if event.state != 'draft' or event.amount <= 0:
                raise ValidationError('Post a draft transaction with a positive amount.')
            self.env.cr.execute('UPDATE car_rental_rental SET id = id WHERE id = %s', [event.rental_id.id])
            event.rental_id.deposit_transaction_ids.invalidate_recordset(['state', 'amount', 'kind'])
            event.rental_id._compute_deposits()
            rental = event.rental_id
            journal = event.company_id.cr_cash_journal_id
            liability = event.company_id.cr_deposit_account_id
            if not journal or not journal.default_account_id or not liability:
                raise ValidationError('Configure the deposit liability account and bank/cash journal first.')
            partner = rental.customer_id._ensure_partner()
            bank = journal.default_account_id
            debit, credit = bank, liability
            if event.kind == 'collect':
                if rental.status != 'draft' or event.amount > rental.deposit_required - rental.deposit_collected + 0.005:
                    raise ValidationError('Collect deposits before pickup, up to the required deposit amount.')
            else:
                if rental.status != 'returned' or not rental.return_inspection_done or event.amount > rental.deposit_held + 0.005:
                    raise ValidationError('Settlement requires a returned and inspected rental, and cannot exceed the deposit held.')
                if event.kind == 'refund':
                    unresolved = rental.damage_ids.filtered(lambda d: d.state == 'draft' or (d.cost > 0 and (not d.invoice_id or d.invoice_id.state != 'posted' or d.invoice_id.amount_residual > 0)))
                    if unresolved:
                        raise ValidationError('Assess damages and apply the deposit to approved damage invoices before refunding.')
                    debit, credit = liability, bank
                else:
                    damage = event.damage_id
                    if not damage or damage.rental_id != rental or damage.state == 'draft' or damage.invoice_id.state != 'posted':
                        raise ValidationError('Choose an approved damage case with a posted invoice for this rental.')
                    if event.amount > damage.invoice_id.amount_residual + 0.005:
                        raise ValidationError('Deposit retention cannot exceed the damage invoice balance.')
                    debit = liability
                    credit = damage.invoice_id.line_ids.filtered(lambda l: l.account_id.account_type == 'asset_receivable')[:1].account_id
            move = _journal_entry(event.env, event.company_id, journal, '%s: %s' % (rental.reference, event.kind), event.date, debit, credit, event.amount, partner)
            super(Deposit, event).write({'state': 'posted', 'account_move_id': move.id})
            if event.kind == 'retain':
                lines = event.damage_id.invoice_id.line_ids.filtered(lambda l: l.account_id == credit)
                (lines + move.line_ids.filtered(lambda l: l.account_id == credit)).reconcile()

    @api.model_create_multi
    def create(self, vals_list):
        if any(v.get('state', 'draft') != 'draft' or v.get('account_move_id') for v in vals_list):
            raise ValidationError('Create a draft deposit transaction first.')
        return super().create(vals_list)

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
