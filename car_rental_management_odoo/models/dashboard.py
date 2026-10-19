from odoo import models, fields


class CarRentalDashboard(models.Model):
    _name = 'car.rental.dashboard'
    _description = 'Car Rental Dashboard'

    name = fields.Char(
        string='Name',
        default='Car Rental Dashboard'
    )

    total_vehicles = fields.Integer(
        string='Total Vehicles',
        compute='_compute_dashboard'
    )

    available_vehicles = fields.Integer(
        string='Available Vehicles',
        compute='_compute_dashboard'
    )

    rented_vehicles = fields.Integer(
        string='Rented Vehicles',
        compute='_compute_dashboard'
    )

    total_customers = fields.Integer(
        string='Total Customers',
        compute='_compute_dashboard'
    )

    ongoing_rentals = fields.Integer(
        string='Ongoing Rentals',
        compute='_compute_dashboard'
    )

    revenue = fields.Float(
        string='Revenue',
        compute='_compute_dashboard'
    )

    def _compute_dashboard(self):
        Vehicle = self.env['fleet.vehicle']
        Customer = self.env['res.partner']
        Rental = self.env['car.rental.rental']
        Payment = self.env['account.payment']

        total_vehicles = Vehicle.search_count([])

        available_vehicles = Vehicle.search_count([
            ('rental_status', '=', 'available')
        ])

        rented_vehicles = Vehicle.search_count([
            ('rental_status', '=', 'rented')
        ])

        total_customers = Customer.search_count([('rental_cin', '!=', False)])

        ongoing_rentals = Rental.search_count([
            ('status', '=', 'ongoing')
        ])

        payments = Payment.search([
            ('car_rental_id', '!=', False),
            ('state', '=', 'paid'),
        ])

        revenue = sum(payments.mapped('amount'))

        for record in self:
            record.total_vehicles = total_vehicles
            record.available_vehicles = available_vehicles
            record.rented_vehicles = rented_vehicles
            record.total_customers = total_customers
            record.ongoing_rentals = ongoing_rentals
            record.revenue = revenue