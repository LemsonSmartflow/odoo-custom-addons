"""Wizard for creating a rental agreement from a template, customer and vehicle."""
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class RentalAgreementCreateWizard(models.TransientModel):
    _name = 'rental.agreement.create.wizard'
    _description = 'Create Rental Agreement'

    template_id = fields.Many2one(
        'rental.agreement.template', string='Agreement Template', required=True,
        domain="[('state', '=', 'active'), '|', ('company_id', '=', False), "
               "('company_id', '=', company_id)]")
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    partner_id = fields.Many2one('res.partner', string='Customer', required=True,
                                 domain="[('rental_enabled', '=', True)]")
    vehicle_id = fields.Many2one('fleet.vehicle', string='Vehicle', required=True,
                                 domain="[('rental_status', '=', 'available')]")
    destination_id = fields.Many2one('car.rental.zone', string='Destination', required=True)
    pickup_datetime = fields.Datetime(
        string='Delivery Date', default=lambda self: fields.Datetime.now() + timedelta(days=1))
    number_of_days = fields.Integer(string='Lease Period (24-hour days)', default=1, required=True)
    delivery_place = fields.Char(string='Delivery Place', required=True)

    @api.onchange('vehicle_id')
    def _onchange_vehicle(self):
        if self.vehicle_id and not self.delivery_place:
            self.delivery_place = self.destination_id.name or False

    def action_create(self):
        self.ensure_one()
        if self.number_of_days < 1:
            raise ValidationError(_('The lease period must be at least one day.'))
        reservation = self.env['car.rental.reservation'].create({
            'company_id': self.company_id.id,
            'partner_id': self.partner_id.id,
            'vehicle_id': self.vehicle_id.id,
            'category_id': self.vehicle_id.rental_category_id.id,
            'destination_id': self.destination_id.id,
            'pickup_datetime': self.pickup_datetime,
            'number_of_days': self.number_of_days,
            'expected_return_datetime': self.pickup_datetime + timedelta(days=self.number_of_days),
        })
        reservation.action_confirm()
        rental = self.env['car.rental.rental'].create({
            'reservation_id': reservation.id,
            'initial_mileage': self.vehicle_id.odometer,
        })
        journey_action = reservation.action_booking_journey()
        journey = self.env['car.rental.journey'].browse(journey_action['res_id'])
        agreement = self.env['rental.agreement'].create({
            'rental_id': rental.id,
            'delivery_place': self.delivery_place,
        })
        agreement._snapshot_template(self.template_id,
                                     self.template_id._prepare_values(rental, journey))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'rental.agreement',
            'view_mode': 'form',
            'res_id': agreement.id,
            'target': 'current',
        }
