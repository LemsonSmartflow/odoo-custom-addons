# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import _, api, fields, models
from odoo.exceptions import UserError

DEPOSIT_STATUSES = [
    ('not_required', 'Not Required'),
    ('required', 'Required'),
    ('collected', 'Collected'),
    ('partially_applied', 'Partially Applied'),
    ('refund_pending', 'Refund Pending'),
    ('refunded', 'Refunded'),
    ('forfeited', 'Forfeited'),
]


class CarRentalDeposit(models.Model):
    _name = 'car.rental.deposit'
    _description = 'Rental Deposit'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'
    _rec_names_search = ['name']

    name = fields.Char(
        string='Reference', default=lambda self: _('New'), copy=False, required=True)
    rental_order_id = fields.Many2one(
        'sale.order', string='Rental Order', required=True, ondelete='cascade')
    vehicle_id = fields.Many2one(
        related='rental_order_id.allocated_vehicle_id', string='Vehicle', store=True)
    customer_id = fields.Many2one(
        'res.partner', string='Customer', required=True, tracking=True)
    amount = fields.Monetary(string='Deposit Amount', currency_field='currency_id', tracking=True)
    applied_amount = fields.Monetary(
        string='Applied Amount', currency_field='currency_id', readonly=True, copy=False)
    refunded_amount = fields.Monetary(
        string='Refunded Amount', currency_field='currency_id', readonly=True, copy=False)
    remaining_amount = fields.Monetary(
        string='Remaining', currency_field='currency_id', compute='_compute_remaining')
    status = fields.Selection(
        selection=DEPOSIT_STATUSES, string='Status', default='required', tracking=True, copy=False,
        help='Required > Collected > Partially Applied > Refund Pending > Refunded / Forfeited.')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
    currency_id = fields.Many2one(
        related='company_id.currency_id', store=True, readonly=True)
    journal_entry_id = fields.Many2one('account.move', string='Receipt Entry', readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                seq = self.env['ir.sequence'].next_by_code('car.rental.deposit') or _('New')
                vals['name'] = seq
        return super().create(vals_list)

    @api.depends('amount', 'applied_amount', 'refunded_amount')
    def _compute_remaining(self):
        for deposit in self:
            deposit.remaining_amount = deposit.amount - deposit.applied_amount - deposit.refunded_amount

    def _sync_from_order(self):
        """Refresh deposit amounts from the linked rental order (rate snapshot)."""
        for deposit in self:
            order = deposit.rental_order_id
            if deposit.status == 'required':
                deposit.amount = order.security_deposit_amount
                if order.rental_vehicle_category_id.deposit_method == 'none' or order.security_deposit_amount <= 0:
                    deposit.status = 'not_required'

    def _get_posting_accounts(self):
        """Deposit receipt/posting: debit bank/cash journal account, credit the deposit liability."""
        self.ensure_one()
        company = self.company_id
        liability = company.rental_deposit_liability_account_id
        journal = company.rental_deposit_journal_id
        if not liability or not journal:
            raise UserError(_(
                'Deposit posting is not configured for company %s. Ask the accountant to set the '
                '"Customer Rental Deposits" liability account and the deposit bank/cash journal in '
                'Car Rental > Configuration > Rental Settings.', company.name))
        return journal.default_account_id, liability, journal

    def _post_deposit_move(self, debit_account, credit_account, journal, amount, label):
        """Create and post a two-line journal entry (deposit lifecycle accounting)."""
        self.ensure_one()
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': fields.Date.context_today(self),
            'ref': _('%s - %s', label, self.rental_order_id.name),
            'line_ids': [
                fields.Command.create({
                    'name': label,
                    'account_id': debit_account.id,
                    'debit': amount,
                    'credit': 0.0,
                }),
                fields.Command.create({
                    'name': label,
                    'account_id': credit_account.id,
                    'debit': 0.0,
                    'credit': amount,
                }),
            ],
        })
        move.action_post()
        return move

    def action_mark_collected(self):
        """Deposit received: Dr Bank/Cash, Cr Customer Rental Deposits (liability)."""
        for deposit in self:
            if deposit.status != 'required':
                raise UserError(_('Only deposits awaiting collection can be marked as collected.'))
            if deposit.amount <= 0:
                raise UserError(_('The deposit amount must be positive.'))
            debit_account, credit_account, journal = deposit._get_posting_accounts()
            deposit.journal_entry_id = deposit._post_deposit_move(
                debit_account, credit_account, journal, deposit.amount,
                _('Security deposit received'))
            deposit.status = 'collected'
            template = self.env.ref(
                'car_rental_management.mail_template_deposit_settlement', raise_if_not_found=False)
            if template:
                template.send_mail(deposit.id, force_send=False)

    def action_apply(self, amount, damage=None):
        """Apply part of the deposit (Dr Deposit liability, Cr approved recovery account)."""
        for deposit in self:
            if deposit.status not in ('collected', 'partially_applied'):
                raise UserError(_('Only collected deposits can be applied.'))
            company = deposit.company_id
            recovery = company.rental_recovery_income_account_id
            if not recovery:
                raise UserError(_(
                    'The "Damage/Recovery Income" account is not configured for company %s.',
                    company.name))
            _debit_account, liability_account, journal = deposit._get_posting_accounts()
            deposit._post_deposit_move(
                liability_account, recovery, journal, amount,
                _('Deposit applied%s', ' - %s' % damage.name if damage else ''))
            deposit.applied_amount += amount
            if deposit.applied_amount >= deposit.amount:
                deposit.status = 'refund_pending'
            else:
                deposit.status = 'partially_applied'
            if damage:
                damage.message_post(body=_('Deposit of %s applied.', amount))

    def action_request_refund(self):
        for deposit in self:
            if deposit.status not in ('collected', 'partially_applied'):
                raise UserError(_('Only collected deposits can be queued for refund.'))
            deposit.status = 'refund_pending'

    def action_refund(self):
        """Deposit refunded: Dr Customer Rental Deposits (liability), Cr Bank/Cash."""
        for deposit in self:
            if deposit.status != 'refund_pending':
                raise UserError(_('Only deposits pending refund can be refunded.'))
            refundable = deposit.remaining_amount
            if refundable <= 0:
                raise UserError(_('Nothing remains to refund on deposit %s.', deposit.name))
            bank_account, liability_account, journal = deposit._get_posting_accounts()
            deposit._post_deposit_move(
                liability_account, bank_account, journal, refundable,
                _('Security deposit refunded'))
            deposit.refunded_amount = refundable
            deposit.status = 'refunded'
            template = self.env.ref(
                'car_rental_management.mail_template_deposit_settlement', raise_if_not_found=False)
            if template:
                template.send_mail(deposit.id, force_send=False)

    def action_forfeit(self):
        """Deposit retained under policy: Dr Deposit liability, Cr approved recovery account."""
        for deposit in self:
            if deposit.status not in ('refund_pending', 'collected', 'partially_applied'):
                raise UserError(_('Only collected deposits can be forfeited.'))
            company = deposit.company_id
            recovery = company.rental_recovery_income_account_id
            if not recovery:
                raise UserError(_(
                    'The "Damage/Recovery Income" account is not configured for company %s.',
                    company.name))
            forfeit_amount = deposit.remaining_amount
            if forfeit_amount <= 0:
                raise UserError(_('Nothing remains to forfeit on deposit %s.', deposit.name))
            _debit_account, liability_account, journal = deposit._get_posting_accounts()
            deposit._post_deposit_move(
                liability_account, recovery, journal, forfeit_amount,
                _('Security deposit forfeited under policy'))
            deposit.applied_amount += forfeit_amount
            deposit.status = 'forfeited'
