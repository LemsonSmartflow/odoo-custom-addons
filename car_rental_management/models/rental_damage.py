# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import _, api, fields, models
from odoo.exceptions import UserError

DAMAGE_TYPES = [
    ('scratch', 'Scratch'),
    ('dent', 'Dent'),
    ('crack', 'Crack / Glass'),
    ('mechanical', 'Mechanical'),
    ('interior', 'Interior'),
    ('tyre', 'Tyre / Wheel'),
    ('missing_equipment', 'Missing Equipment'),
    ('other', 'Other'),
]

DAMAGE_SEVERITIES = [
    ('minor', 'Minor'),
    ('moderate', 'Moderate'),
    ('major', 'Major'),
]


class CarRentalDamage(models.Model):
    _name = 'car.rental.damage'
    _description = 'Damage Assessment'
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
        related='rental_order_id.partner_id', string='Customer', store=True)
    inspection_id = fields.Many2one('car.rental.inspection', string='Return Inspection')
    damage_type = fields.Selection(selection=DAMAGE_TYPES, string='Damage Type', required=True)
    description = fields.Text(string='Description')
    severity = fields.Selection(selection=DAMAGE_SEVERITIES, string='Severity', default='minor', required=True)
    estimated_cost = fields.Monetary(string='Estimated Cost', currency_field='currency_id')
    final_cost = fields.Monetary(string='Final Cost', currency_field='currency_id')
    customer_charge = fields.Monetary(
        string='Customer Charge', currency_field='currency_id',
        help='Amount recovered from the customer (may differ from repair cost per company policy).')
    deposit_applied = fields.Monetary(
        string='Deposit Applied', currency_field='currency_id', copy=False, tracking=True,
        help='Amount deducted from the security deposit.')
    additional_invoice_id = fields.Many2one(
        'account.move', string='Additional Invoice', readonly=True, copy=False)
    approval_status = fields.Selection(
        selection=[('draft', 'Draft'), ('approved', 'Approved'), ('rejected', 'Rejected')],
        string='Approval Status', default='draft', tracking=True, copy=False)
    approved_by = fields.Many2one('res.users', string='Approved By', readonly=True, copy=False)
    approved_date = fields.Datetime(string='Approved On', readonly=True, copy=False)
    attachment_ids = fields.Many2many('ir.attachment', string='Photos')
    company_id = fields.Many2one(
        related='rental_order_id.company_id', store=True, readonly=True)
    currency_id = fields.Many2one(
        related='rental_order_id.currency_id', store=True, readonly=True)
    repair_request_id = fields.Many2one('maintenance.request', string='Maintenance Request', readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                seq = self.env['ir.sequence'].next_by_code('car.rental.damage') or _('New')
                vals['name'] = seq
        return super().create(vals_list)

    def _sync_from_inspection(self, inspection):
        """Create damage assessments for the damage lines found at return."""
        if self.filtered(lambda damage: damage.inspection_id == inspection):
            return
        for line in inspection.line_ids.filtered(lambda line: line.result == 'damage'):
            self.env['car.rental.damage'].create({
                'rental_order_id': inspection.rental_order_id.id,
                'inspection_id': inspection.id,
                'damage_type': 'other',
                'description': '%s%s' % (line.item, ' - %s' % line.notes if line.notes else ''),
                'severity': 'minor',
            })

    def _is_rental_manager(self):
        return self.env.user.has_group('car_rental_management.car_rental_group_manager')

    def action_approve(self):
        for damage in self:
            if damage.approval_status != 'draft':
                raise UserError(_('Only draft damage assessments can be approved.'))
            if not damage._is_rental_manager():
                raise UserError(_('Only Rental Managers may approve damage assessments.'))
            damage.write({
                'approval_status': 'approved',
                'approved_by': damage.env.user.id,
                'approved_date': fields.Datetime.now(),
            })

    def action_reject(self):
        for damage in self:
            if damage.approval_status != 'draft':
                raise UserError(_('Only draft damage assessments can be rejected.'))
            if not damage._is_rental_manager():
                raise UserError(_('Only Rental Managers may reject damage assessments.'))
            damage.approval_status = 'rejected'

    def action_apply_deposit(self):
        """Deduct the damage charge from the security deposit (liability)."""
        for damage in self:
            if damage.approval_status != 'approved':
                raise UserError(_('Approve the damage assessment before applying the deposit.'))
            if damage.customer_charge <= 0:
                raise UserError(_('Set the customer charge before applying the deposit.'))
            deposit = damage.rental_order_id.deposit_ids[:1]
            if not deposit or deposit.status not in ('collected', 'partially_applied'):
                raise UserError(_(
                    'No collected security deposit is available on rental order %s.',
                    damage.rental_order_id.name))
            already_applied = sum(damage.rental_order_id.damage_ids.mapped('deposit_applied'))
            remaining = deposit.amount - already_applied
            applied = min(damage.customer_charge, remaining)
            if applied <= 0:
                raise UserError(_(
                    'The security deposit on %s is fully applied. Invoice the balance instead.',
                    damage.rental_order_id.name))
            damage.deposit_applied = applied
            deposit.action_apply(applied, damage)

    def action_create_balance_invoice(self):
        """Invoice the charge balance exceeding the applied deposit."""
        for damage in self:
            if damage.approval_status != 'approved':
                raise UserError(_('Approve the damage assessment before invoicing.'))
            if damage.additional_invoice_id:
                raise UserError(_('A balance invoice already exists for this damage assessment.'))
            balance = damage.customer_charge - damage.deposit_applied
            if balance <= 0:
                raise UserError(_('The deposit covers the full charge. Nothing to invoice.'))
            damage.additional_invoice_id = damage._create_recovery_invoice(
                balance, _('Damage recovery - %s', damage.name))

    def _create_recovery_invoice(self, amount, label):
        """Create a customer invoice line using the company recovery income account."""
        self.ensure_one()
        company = self.rental_order_id.company_id
        account = company.rental_recovery_income_account_id
        if not account:
            raise UserError(_(
                'The "Damage/Recovery Income" account is not configured for company %s. '
                'Ask the accountant to set it in Car Rental > Configuration > Rental Settings.',
                company.name))
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.rental_order_id.partner_id.id,
            'invoice_date': fields.Date.context_today(self),
            'company_id': company.id,
            'invoice_line_ids': [fields.Command.create({
                'name': label,
                'quantity': 1,
                'price_unit': amount,
                'account_id': account.id,
            })],
        })
        self.message_post(body=_('Recovery invoice %s created for %s.', invoice.name, amount))
        return invoice

    def action_create_repair_request(self):
        """Create a maintenance request for the repair."""
        for damage in self:
            if damage.repair_request_id:
                continue
            vehicle = damage.vehicle_id
            if not vehicle:
                raise UserError(_('No vehicle is linked to this rental order.'))
            request = self.env['maintenance.request'].create({
                'name': _('Repair after damage %(damage)s - %(vehicle)s',
                          damage=damage.name, vehicle=vehicle.display_name),
                'maintenance_type': 'corrective',
                'request_date': fields.Date.context_today(self),
                'rental_vehicle_id': vehicle.id,
                'company_id': vehicle.company_id.id,
            })
            damage.repair_request_id = request
