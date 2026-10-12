from odoo import models, fields


class RentalVehicle(models.Model):
    _name = 'car.rental.vehicle'
    _description = 'Rental Vehicle'
    _rec_name = 'registration_number'

    image_1920 = fields.Image(
        string='Vehicle Photo',
        max_width=1920,
        max_height=1920,
    )

    registration_number = fields.Char(
        string='Registration Number',
        required=True
    )

    brand = fields.Char(
        string='Brand',
        required=True
    )

    model = fields.Char(
        string='Model',
        required=True
    )

    year = fields.Integer(
        string='Year'
    )

    color = fields.Char(
        string='Color'
    )

    category = fields.Char(
        string='Category'
    )

    fuel_type = fields.Selection([
        ('petrol', 'Petrol'),
        ('diesel', 'Diesel'),
        ('electric', 'Electric'),
        ('hybrid', 'Hybrid'),
    ], string='Fuel Type')

    transmission = fields.Selection([
        ('manual', 'Manual'),
        ('automatic', 'Automatic'),
    ], string='Transmission')

    seats = fields.Integer(
        string='Number of Seats'
    )

    mileage = fields.Float(
        string='Mileage'
    )

    daily_price = fields.Float(
        string='Daily Price',
        default=0,
        help='Legacy vehicle rate. New reservations use approved destination pricing rules.'
    )

    status = fields.Selection([
        ('available', 'Available'),
        ('rented', 'Rented'),
        ('maintenance', 'Maintenance'),
    ],
        string='Status',
        default='available',
        required=True
    )
