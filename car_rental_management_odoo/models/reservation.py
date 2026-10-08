from odoo import models, fields, api
from odoo.exceptions import ValidationError


class RentalReservation(models.Model):
    _name = 'car.rental.reservation'
    _description = 'Car Rental Reservation'
    _rec_name = 'reference'

    # =========================
    # FIELDS
    # =========================

    reference = fields.Char(
        string='Reference',
        default='New',
        required=True
    )

    customer_id = fields.Many2one(
        'car.rental.customer',
        string='Customer',
        required=True
    )

    vehicle_id = fields.Many2one(
        'car.rental.vehicle',
        string='Vehicle',
        required=True
    )

    start_date = fields.Date(
        string='Start Date',
        required=True
    )

    end_date = fields.Date(
        string='End Date',
        required=True
    )

    number_of_days = fields.Integer(
        string='Number of Days',
        compute='_compute_number_of_days',
        store=True
    )

    amount = fields.Float(
        string='Amount',
        compute='_compute_amount',
        store=True
    )

    status = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('cancelled', 'Cancelled'),
    ],
        string='Status',
        default='draft',
        required=True
    )

    # =========================
    # COMPUTED FIELDS
    # =========================

    @api.depends('start_date', 'end_date')
    def _compute_number_of_days(self):
        for record in self:

            if (
                record.start_date
                and record.end_date
                and record.end_date > record.start_date
            ):
                record.number_of_days = (
                    record.end_date - record.start_date
                ).days

            else:
                record.number_of_days = 0

    @api.depends(
        'number_of_days',
        'vehicle_id.daily_price'
    )
    def _compute_amount(self):
        for record in self:

            if record.vehicle_id:
                record.amount = (
                    record.number_of_days
                    * record.vehicle_id.daily_price
                )

            else:
                record.amount = 0.0

    # =========================
    # WORKFLOW
    # =========================

    def action_confirm(self):
        for record in self:
            record.status = 'confirmed'

    def action_cancel(self):
        for record in self:
            record.status = 'cancelled'

    def action_reset_draft(self):
        for record in self:
            record.status = 'draft'

    # =========================
    # RG02
    # END DATE > START DATE
    # =========================

    @api.constrains('start_date', 'end_date')
    def _check_dates(self):
        for record in self:

            if (
                record.start_date
                and record.end_date
                and record.end_date <= record.start_date
            ):
                raise ValidationError(
                    'End Date must be greater than Start Date.'
                )

    # =========================
    # RG03
    # DRIVING LICENSE VALID
    # =========================

    @api.constrains(
        'customer_id',
        'start_date'
    )
    def _check_driving_license(self):
        for record in self:

            if (
                record.customer_id
                and record.start_date
                and record.customer_id.license_expiry
            ):

                if (
                    record.customer_id.license_expiry
                    < record.start_date
                ):
                    raise ValidationError(
                        'The customer cannot rent a vehicle '
                        'because the driving license is expired.'
                    )

    # =========================
    # RG04
    # VEHICLE IN MAINTENANCE
    # CANNOT BE RESERVED
    # =========================

    @api.constrains('vehicle_id')
    def _check_vehicle_maintenance(self):
        for record in self:

            if (
                record.vehicle_id
                and record.vehicle_id.status == 'maintenance'
            ):
                raise ValidationError(
                    'This vehicle is in maintenance '
                    'and cannot be reserved.'
                )

    # =========================
    # RG01 + RG07
    # CHECK VEHICLE AVAILABILITY
    # CANCELLED RESERVATIONS
    # DO NOT BLOCK THE VEHICLE
    # =========================

    @api.constrains(
        'vehicle_id',
        'start_date',
        'end_date',
        'status'
    )
    def _check_vehicle_availability(self):
        for record in self:

            # Cancelled reservation does not block vehicle
            if record.status == 'cancelled':
                continue

            if (
                not record.vehicle_id
                or not record.start_date
                or not record.end_date
            ):
                continue

            conflicting_reservation = self.search([
                (
                    'vehicle_id',
                    '=',
                    record.vehicle_id.id
                ),

                (
                    'id',
                    '!=',
                    record.id
                ),

                (
                    'status',
                    '!=',
                    'cancelled'
                ),

                (
                    'start_date',
                    '<=',
                    record.end_date
                ),

                (
                    'end_date',
                    '>=',
                    record.start_date
                ),
            ], limit=1)

            if conflicting_reservation:
                raise ValidationError(
                    'This vehicle is already reserved '
                    'during the selected period.'
                )