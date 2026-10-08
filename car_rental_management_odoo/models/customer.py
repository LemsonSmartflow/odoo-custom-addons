from odoo import models, fields


class RentalCustomer(models.Model):
    _name = "car.rental.customer"
    _description = "Rental Customer"
    _rec_name = 'first_name'

    first_name = fields.Char(
        string="First Name",
        required=True
    )

    last_name = fields.Char(
        string="Last Name",
        required=True
    )

    cin = fields.Char(
        string="CIN / Passport",
        required=True
    )

    phone = fields.Char(
        string="Phone"
    )

    email = fields.Char(
        string="Email"
    )

    address = fields.Text(
        string="Address"
    )

    driving_license = fields.Char(
        string="Driving License",
        required=True
    )

    license_expiry = fields.Date(
        string="License Expiry",
        required=True
    )

    active = fields.Boolean(
        default=True
    )