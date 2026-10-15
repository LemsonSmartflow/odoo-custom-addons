from odoo import api, fields, models
from odoo.exceptions import ValidationError
from .pricing import require_role


class Collection(models.TransientModel):
    _name = 'car.rental.collection'
    _description = 'Rental Payment and Security Deposit'

    rental_id = fields.Many2one('car.rental.rental', required=True, readonly=True)
    company_id = fields.Many2one(related='rental_id.company_id')
    currency_id = fields.Many2one(related='rental_id.currency_id')
    journal_id = fields.Many2one(related='company_id.cr_cash_journal_id', string='Receiving Journal')
    customer_id = fields.Many2one(related='rental_id.customer_id')
    rental_due = fields.Monetary(compute='_compute_split', string='Rental Balance')
    deposit_due = fields.Monetary(compute='_compute_split', string='Security Deposit Remaining')
    total_due = fields.Monetary(compute='_compute_split', string='Total Remaining')
    amount = fields.Monetary(required=True, string='Amount Received')
    date = fields.Date(required=True, default=fields.Date.context_today, string='Payment Date')
    payment_method = fields.Selection([('cash', 'Cash'), ('card', 'Card'), ('bank_transfer', 'Bank Transfer')], required=True, default='bank_transfer')
    reference = fields.Char(string='Bank / Receipt Reference')
    to_deposit = fields.Monetary(compute='_compute_split', string='Allocated to Refundable Deposit')
    to_rental = fields.Monetary(compute='_compute_split', string='Allocated to Rental Payment')
    remaining = fields.Monetary(compute='_compute_split', string='Remaining After This Payment')
    posted = fields.Boolean(readonly=True)

    @api.model
    def default_get(self, names):
        result = super().default_get(names)
        rental = self.env['car.rental.rental'].browse(result.get('rental_id') or self.env.context.get('default_rental_id')).exists()
        if rental and 'amount' in names:
            result['amount'] = max(rental.balance_due, 0) + (max(rental.deposit_required - rental.deposit_collected, 0) if rental.status == 'draft' else 0)
        return result

    @api.depends('rental_id', 'amount', 'rental_id.balance_due', 'rental_id.deposit_collected', 'rental_id.status')
    def _compute_split(self):
        for wizard in self:
            rental = wizard.rental_id
            wizard.rental_due = max(rental.balance_due, 0)
            wizard.deposit_due = max(rental.deposit_required - rental.deposit_collected, 0) if rental.status == 'draft' else 0
            wizard.total_due = wizard.rental_due + wizard.deposit_due
            wizard.to_deposit = min(max(wizard.amount, 0), wizard.deposit_due)
            wizard.to_rental = max(wizard.amount - wizard.to_deposit, 0)
            wizard.remaining = max(wizard.total_due - wizard.amount, 0)

    @api.model_create_multi
    def create(self, vals_list):
        if any(vals.get('posted') for vals in vals_list):
            raise ValidationError('Use Record Payment to post a collection.')
        return super().create(vals_list)

    def write(self, vals):
        if 'posted' in vals or any(self.mapped('posted')):
            raise ValidationError('This collection has already been recorded.')
        return super().write(vals)

    def action_post(self):
        require_role(self.env, 'group_rental_accountant')
        self.ensure_one()
        self.env.cr.execute('SELECT id FROM car_rental_collection WHERE id=%s FOR UPDATE', [self.id])
        self.invalidate_recordset()
        if self.posted:
            return {'type': 'ir.actions.act_window_close'}
        rental = self.rental_id
        self.env.cr.execute('SELECT id FROM car_rental_rental WHERE id=%s FOR UPDATE', [rental.id])
        rental.invalidate_recordset()
        self._compute_split()
        currency = self.currency_id
        if rental.status == 'closed' or rental.reservation_id.status != 'confirmed':
            raise ValidationError('Collect payment against an open, confirmed rental.')
        if currency.compare_amounts(self.amount, 0) <= 0 or currency.compare_amounts(self.amount, self.total_due) > 0:
            raise ValidationError('Enter a positive amount no greater than the remaining rental and deposit total. Reopen the form if another payment was just recorded.')
        if currency.compare_amounts(self.amount, currency.round(self.amount)) != 0:
            raise ValidationError('Use the currency rounding for the payment amount.')
        if self.to_deposit and rental.deposit_collected <= 0 and currency.compare_amounts(self.to_deposit, rental.reservation_id.quoted_daily_rate * 0.5) < 0:
            raise ValidationError('The first collection must cover at least 50% of one daily rate as security deposit.')
        # Savepoint makes invoice creation and both entries an all-or-nothing operation.
        with self.env.cr.savepoint():
            rental.action_invoice()
            invoice = rental.invoice_ids.filtered(lambda m: m.rental_invoice_kind == 'rental' and m.state != 'cancel' and m.move_type == 'out_invoice')
            if len(invoice) != 1:
                raise ValidationError('Resolve duplicate or missing rental invoices before collecting payment.')
            if invoice.state == 'draft':
                invoice.action_post()
            deposit_amount, rental_amount = currency.round(self.to_deposit), currency.round(self.to_rental)
            if currency.compare_amounts(rental_amount, invoice.amount_residual) > 0:
                raise ValidationError('The invoice balance changed. Reopen the collection form.')
            if deposit_amount:
                deposit = self.env['car.rental.deposit.transaction'].create({
                    'rental_id': rental.id, 'kind': 'collect', 'amount': deposit_amount, 'date': self.date,
                    'collection_method': self.payment_method, 'collection_reference': self.reference})
                deposit.action_post()
            if rental_amount:
                receipt = self.env['car.rental.payment'].create({
                    'rental_id': rental.id, 'paid_amount': rental_amount, 'payment_date': self.date,
                    'payment_method': self.payment_method, 'collection_reference': self.reference})
                receipt.action_post_receipt()
            super().write({'posted': True})
            rental.message_post(body='Combined collection: %s %s; security deposit %s; rental payment %s. Method: %s. Reference: %s.' %
                                (currency.round(self.amount), currency.name, deposit_amount, rental_amount, self.payment_method, self.reference or '-'))
        return {'type': 'ir.actions.act_window_close'}


class Rental(models.Model):
    _inherit = 'car.rental.rental'

    def action_collect_payment(self):
        require_role(self.env, 'group_rental_accountant')
        self.ensure_one()
        deposit_due = max(self.deposit_required - self.deposit_collected, 0) if self.status == 'draft' else 0
        if self.currency_id.is_zero(max(self.balance_due, 0) + deposit_due):
            raise ValidationError('The rental payment and security deposit have already been collected.')
        return {'type': 'ir.actions.act_window', 'name': 'Payment & Security Deposit',
                'res_model': 'car.rental.collection', 'view_mode': 'form', 'target': 'new',
                'context': {'default_rental_id': self.id, 'allowed_company_ids': [self.company_id.id]}}

    def action_record_payment(self):
        return self.action_collect_payment()


class Journey(models.Model):
    _inherit = 'car.rental.journey'

    def action_collect_payment(self):
        self.ensure_one()
        return self.rental_id.action_collect_payment()


class Deposit(models.Model):
    _inherit = 'car.rental.deposit.transaction'
    collection_method = fields.Selection([('cash', 'Cash'), ('card', 'Card'), ('bank_transfer', 'Bank Transfer')], readonly=True)
    collection_reference = fields.Char(readonly=True)


class Payment(models.Model):
    _inherit = 'car.rental.payment'
    collection_reference = fields.Char(readonly=True, string='Bank / Receipt Reference')
