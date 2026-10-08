# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import _, api, fields, models
from odoo.exceptions import UserError

CHARGE_TYPES = [
    ('late_return', 'Late Return'),
    ('delivery', 'Delivery'),
    ('return_fee', 'Return Fee'),
    ('after_hours', 'After Hours'),
    ('additional_driver', 'Additional Driver'),
    ('cross_border', 'Cross Border'),
    ('cleaning', 'Cleaning'),
    ('fuel_recovery', 'Fuel Recovery'),
    ('damage', 'Approved Damage'),
    ('other', 'Other'),
]


class CarRentalCharge(models.Model):
    _name = 'car.rental.charge'
    _description = 'Additional Rental Charge'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'
    _rec_names_search = ['name', 'description']

    name = fields.Char(
        string='Reference', default=lambda self: _('New'), copy=False, required=True)
    rental_order_id = fields.Many2one(
        'sale.order', string='Rental Order', required=True, ondelete='cascade')
    vehicle_id = fields.Many2one(
        related='rental_order_id.allocated_vehicle_id', string='Vehicle', store=True)
    charge_type = fields.Selection(selection=CHARGE_TYPES, string='Charge Type', required=True)
    description = fields.Char(string='Description')
    quantity = fields.Float(string='Quantity', default=1.0, required=True)
    unit_amount = fields.Monetary(string='Unit Amount', currency_field='currency_id', required=True)
    amount = fields.Monetary(
        string='Amount', currency_field='currency_id', compute='_compute_amount', store=True)
    invoice_id = fields.Many2one('account.move', string='Invoice', readonly=True, copy=False)
    is_invoiced = fields.Boolean(compute='_compute_is_invoiced', string='Invoiced', store=True)
    company_id = fields.Many2one(
        related='rental_order_id.company_id', store=True, readonly=True)
    currency_id = fields.Many2one(
        related='rental_order_id.currency_id', store=True, readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                seq = self.env['ir.sequence'].next_by_code('car.rental.charge') or _('New')
                vals['name'] = seq
        return super().create(vals_list)

    @api.depends('quantity', 'unit_amount')
    def _compute_amount(self):
        for charge in self:
            charge.amount = charge.quantity * charge.unit_amount

    @api.depends('invoice_id')
    def _compute_is_invoiced(self):
        for charge in self:
            charge.is_invoiced = bool(charge.invoice_id)

    def action_create_invoice(self):
        """Invoice this charge using the company recovery income account."""
        self.ensure_one()
        if self.invoice_id:
            raise UserError(_('This charge is already invoiced.'))
        if self.amount <= 0:
            raise UserError(_('The charge amount must be positive before invoicing.'))
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
                'name': _('%s - %s', dict(self._fields['charge_type'].selection).get(self.charge_type),
                          self.description or self.name),
                'quantity': self.quantity,
                'price_unit': self.unit_amount,
                'account_id': account.id,
            })],
        })
        self.invoice_id = invoice
        self.message_post(body=_('Invoice %s created.', invoice.name))
