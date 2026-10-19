"""Rental identity and eligibility on standard Contacts."""
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class Partner(models.Model):
    _inherit = 'res.partner'

    rental_postal_address = fields.Text(string='Rental Postal Address')
    rental_enabled = fields.Boolean(string='Enable Rentals for This Company', groups='car_rental_management_odoo.group_car_rental_agent', copy=False)
    rental_cin = fields.Char(string='Omang / Passport Number', groups='car_rental_management_odoo.group_car_rental_agent')
    rental_date_of_birth = fields.Date(string='Date of Birth', groups='car_rental_management_odoo.group_car_rental_agent')
    rental_driving_license = fields.Char(string='Driving Licence Number', groups='car_rental_management_odoo.group_car_rental_agent')
    rental_license_issue_date = fields.Date(string='Licence Date of Issue', groups='car_rental_management_odoo.group_car_rental_agent')
    rental_license_expiry = fields.Date(string='Licence Expiry', groups='car_rental_management_odoo.group_car_rental_agent')
    rental_omang_document_ids = fields.Many2many('ir.attachment', 'rental_partner_omang_rel', string='Omang Documents', groups='car_rental_management_odoo.group_car_rental_agent')
    rental_passport_document_ids = fields.Many2many('ir.attachment', 'rental_partner_passport_rel', string='Passport Documents', groups='car_rental_management_odoo.group_car_rental_agent')
    rental_license_document_ids = fields.Many2many('ir.attachment', 'rental_partner_licence_rel', string='Licence Documents', groups='car_rental_management_odoo.group_car_rental_agent')
    rental_document_ids = fields.Many2many('ir.attachment', 'rental_partner_document_rel', string='Other / Existing Documents', groups='car_rental_management_odoo.group_car_rental_agent')
    rental_reservations_count = fields.Integer(compute='_compute_rental_counts')
    rental_rentals_count = fields.Integer(compute='_compute_rental_counts')

    @api.depends_context('allowed_company_ids')
    def _compute_rental_counts(self):
        for partner in self:
            domain = [('partner_id', '=', partner.id)]
            partner.rental_reservations_count = self.env['car.rental.reservation'].search_count(domain)
            partner.rental_rentals_count = self.env['car.rental.rental'].search_count(domain)

    @api.constrains('rental_date_of_birth', 'rental_license_issue_date', 'rental_license_expiry')
    def _check_rental_profile_dates(self):
        for partner in self:
            if partner.rental_date_of_birth and partner.rental_date_of_birth >= fields.Date.today():
                raise ValidationError(_('Date of birth must be in the past.'))
            if partner.rental_license_issue_date and partner.rental_license_expiry and partner.rental_license_issue_date > partner.rental_license_expiry:
                raise ValidationError(_('Licence expiry must follow its issue date.'))
            if partner.rental_license_issue_date and partner.rental_license_issue_date > fields.Date.today():
                raise ValidationError(_('Licence date of issue cannot be in the future.'))

    def _check_rental_eligibility(self, pickup, return_time):
        self.ensure_one()
        local_pickup = fields.Datetime.context_timestamp(self, pickup).date()
        local_return = fields.Datetime.context_timestamp(self, return_time).date()
        if not all([self.street, self.rental_postal_address, self.rental_date_of_birth,
                    self.rental_license_issue_date, self.rental_driving_license, self.rental_license_expiry]):
            raise ValidationError(_('Complete the contact address, rental postal address, date of birth and licence details before booking.'))
        birthday = self.rental_date_of_birth
        age = local_pickup.year - birthday.year - ((local_pickup.month, local_pickup.day) < (birthday.month, birthday.day))
        if age < 21:
            raise ValidationError(_('The customer must be at least 21 years old on the pickup date.'))
        if self.rental_license_expiry < local_return or self.rental_license_issue_date > local_pickup:
            raise ValidationError(_('The driving licence must be valid throughout the rental period.'))
        if not (self.rental_omang_document_ids or self.rental_passport_document_ids) or not self.rental_license_document_ids:
            raise ValidationError(_('Upload either Omang or passport, plus the driving licence, before confirming the reservation.'))

    @api.constrains('rental_enabled')
    def _check_rental_enabled(self):
        for partner in self:
            if partner.rental_enabled:
                partner._ensure_rental_ready()

    def _ensure_rental_ready(self):
        self.ensure_one()
        if not self.street or not self.rental_postal_address:
            raise ValidationError(_('Enter the physical street address and rental postal address on the Contact before booking.'))
        required = ('rental_cin', 'rental_date_of_birth', 'rental_driving_license',
                    'rental_license_issue_date', 'rental_license_expiry')
        if any(not self[f] for f in required):
            raise ValidationError(_('Complete the ID number, date of birth, licence number, issue date and expiry on the Contact.'))
        return self

    def action_rental_reservations(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reservations'),
            'res_model': 'car.rental.reservation',
            'view_mode': 'list,form',
            'domain': [('partner_id', '=', self.id)],
            'context': {'default_partner_id': self.id},
        }

    def action_rental_rentals(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Rentals'),
            'res_model': 'car.rental.rental',
            'view_mode': 'list,form',
            'domain': [('partner_id', '=', self.id)],
            'context': {'default_partner_id': self.id},
        }

    def action_rental_book(self):
        self.ensure_one()
        self._ensure_rental_ready()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Create a Booking'),
            'res_model': 'car.rental.journey',
            'view_mode': 'form',
            'target': 'current',
            'context': {'default_partner_id': self.id, 'default_company_id': self.env.company.id},
        }
