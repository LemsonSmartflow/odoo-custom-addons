from odoo import models, fields, api
from odoo.exceptions import ValidationError


class CarRental(models.Model):
    _name = 'car.rental.rental'
    _description = 'Car Rental'
    _rec_name = 'reference'

    reference = fields.Char(
        string='Reference',
        default='New',
        required=True
    )

    reservation_id = fields.Many2one(
        'car.rental.reservation',
        string='Reservation',
        required=True
    )

    customer_id = fields.Many2one(
        'car.rental.customer',
        string='Customer',
        related='reservation_id.customer_id',
        store=True,
        readonly=True
    )

    vehicle_id = fields.Many2one(
        'car.rental.vehicle',
        string='Vehicle',
        related='reservation_id.vehicle_id',
        store=True,
        readonly=True
    )

    start_date = fields.Date(
        string='Start Date',
        related='reservation_id.start_date',
        store=True,
        readonly=True
    )

    return_date = fields.Date(
        string='Expected Return Date',
        related='reservation_id.end_date',
        store=True,
        readonly=True
    )

    initial_mileage = fields.Float(
        string='Initial Mileage',
        required=True
    )

    final_mileage = fields.Float(
        string='Final Mileage'
    )

    amount = fields.Float(
        string='Amount',
        related='reservation_id.amount',
        store=True,
        readonly=True
    )

    status = fields.Selection([
        ('draft', 'Draft'),
        ('ongoing', 'Ongoing'),
        ('returned', 'Returned'),
    ],
        string='Status',
        default='draft',
        required=True
    )

    def action_start_rental(self):
        for record in self:

            if record.reservation_id.status != 'confirmed':
                raise ValidationError(
                    'Only a confirmed reservation can become a rental.'
                )

            record.status = 'ongoing'
            record.vehicle_id.status = 'rented'

    def action_return_vehicle(self):
        for record in self:

            if not record.final_mileage:
                raise ValidationError(
                    'Please enter the final mileage.'
                )

            if record.final_mileage < record.initial_mileage:
                raise ValidationError(
                    'Final mileage cannot be lower than initial mileage.'
                )

            record.status = 'returned'

            record.vehicle_id.status = 'available'

            record.vehicle_id.mileage = record.final_mileage