from odoo import models, fields, api
from odoo.exceptions import ValidationError


class CarRentalPayment(models.Model):
    _name = 'car.rental.payment'
    _description = 'Car Rental Payment'
    _rec_name = 'reference'

    reference = fields.Char(
        string='Reference',
        default='New',
        required=True
    )

    rental_id = fields.Many2one(
        'car.rental.rental',
        string='Rental',
        required=True
    )

    payment_date = fields.Date(
        string='Payment Date',
        default=fields.Date.today,
        required=True
    )

    total_amount = fields.Float(
        string='Total Amount',
        related='rental_id.amount',
        store=True,
        readonly=True
    )

    paid_amount = fields.Float(
        string='Paid Amount',
        required=True
    )

    remaining_amount = fields.Float(
        string='Remaining Amount',
        compute='_compute_remaining_amount',
        store=True
    )

    payment_method = fields.Selection([
        ('cash', 'Cash'),
        ('card', 'Card'),
        ('bank_transfer', 'Bank Transfer'),
    ],
        string='Payment Method',
        required=True
    )

    status = fields.Selection([
        ('unpaid', 'Unpaid'),
        ('partial', 'Partially Paid'),
        ('paid', 'Paid'),
    ],
        string='Status',
        compute='_compute_status',
        store=True
    )

    @api.depends('total_amount', 'paid_amount')
    def _compute_remaining_amount(self):
        for record in self:
            record.remaining_amount = max(
                record.total_amount - record.paid_amount,
                0.0
            )

    @api.depends('total_amount', 'paid_amount')
    def _compute_status(self):
        for record in self:

            if record.paid_amount <= 0:
                record.status = 'unpaid'

            elif record.paid_amount < record.total_amount:
                record.status = 'partial'

            else:
                record.status = 'paid'

    @api.constrains('paid_amount', 'total_amount')
    def _check_paid_amount(self):
        for record in self:

            if record.paid_amount < 0:
                raise ValidationError(
                    'Paid Amount cannot be negative.'
                )

            if record.paid_amount > record.total_amount:
                raise ValidationError(
                    'Paid Amount cannot be greater than Total Amount.'
                )