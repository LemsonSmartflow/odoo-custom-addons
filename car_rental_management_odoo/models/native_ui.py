"""Native Contacts/Fleet screens with company-scoped rental extensions.

Rental identity lives directly on res.partner; these are screen affordances only.
"""
from odoo import api, fields, models
from odoo.exceptions import ValidationError
from .workflow import window

STAFF = 'car_rental_management_odoo.group_car_rental_agent'


class Partner(models.Model):
    _inherit = 'res.partner'

    def action_rental_profile(self):
        self.ensure_one()
        return window('Customer', 'res.partner', res_id=self.id)


class ContactSelection(models.AbstractModel):
    _name = 'car.rental.contact.selection'
    _description = 'Contact selection for rental bookings'

    contact_id = fields.Many2one('res.partner', string='Customer', compute='_compute_contact', inverse='_inverse_contact', search='_search_contact')

    @api.depends('partner_id')
    def _compute_contact(self):
        for record in self:
            record.contact_id = record.partner_id

    def _inverse_contact(self):
        pass

    def _search_contact(self, operator, value):
        return [('partner_id', operator, value)]

    @api.onchange('contact_id')
    def _onchange_native_contact(self):
        self.partner_id = self.contact_id

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'contact_id' in vals and 'partner_id' not in vals:
                vals['partner_id'] = vals.pop('contact_id')
        return super().create(vals_list)

    def write(self, vals):
        if 'contact_id' in vals and 'partner_id' not in vals:
            vals = dict(vals, partner_id=vals.pop('contact_id'))
        return super().write(vals)


class Reservation(models.Model):
    _name = 'car.rental.reservation'
    _inherit = ['car.rental.reservation', 'car.rental.contact.selection']


class Journey(models.Model):
    _name = 'car.rental.journey'
    _inherit = ['car.rental.journey', 'car.rental.contact.selection']


class Rental(models.Model):
    _inherit = 'car.rental.rental'
    contact_id = fields.Many2one(related='partner_id', string='Customer')


class Dashboard(models.Model):
    _inherit = 'car.rental.dashboard'

    def action_customers(self):
        return self.env['ir.actions.actions']._for_xml_id('car_rental_management_odoo.action_native_customers')

    def action_vehicles(self):
        return self.env['ir.actions.actions']._for_xml_id('car_rental_management_odoo.action_native_vehicles')

    def action_available(self):
        action = self.action_vehicles()
        ids = self.env['fleet.vehicle'].search([('company_id', '=', self.env.company.id), ('rental_status', '=', 'available')]).ids
        action['domain'] = [('id', 'in', ids)]
        return action

    def action_reserved(self):
        action = self.action_vehicles()
        ids = self.env['fleet.vehicle'].search([('company_id', '=', self.env.company.id), ('rental_status', '=', 'reserved')]).ids
        action['domain'] = [('id', 'in', ids)]
        return action


class Fleet(models.Model):
    _inherit = 'fleet.vehicle'

    def action_enable_rentals(self):
        self.ensure_one()
        if not self.license_plate or not self.model_id:
            raise ValidationError('Enter the registration plate and vehicle model first.')
        if not self.rental_category_id:
            raise ValidationError('Set the rental category first.')
        if self.rental_status == 'setup':
            self.action_activate()
        return window('Vehicle', 'fleet.vehicle', res_id=self.id)

    def action_rental_profile(self):
        self.ensure_one()
        return window('Vehicle', 'fleet.vehicle', res_id=self.id)

    def action_rental_release(self):
        return self.action_release()

    def action_rental_cleaning(self):
        return self.action_mark_cleaning()

    def action_rental_activate(self):
        return self.action_activate()
