"""Rental identity and eligibility on standard Contacts."""
import re

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools.misc import format_date


class Partner(models.Model):
    _inherit = 'res.partner'

    rental_postal_address = fields.Text(string='Rental Postal Address')
    rental_enabled = fields.Boolean(string='Enable Rentals for This Company', groups='car_rental_management_odoo.group_car_rental_agent', copy=False)
    rental_identity_type = fields.Selection(
        [('omang', 'Omang'), ('passport', 'Passport')],
        string='Identity Document',
        default='omang',
        help='Choose the identity document that will be used for this customer.',
        groups='car_rental_management_odoo.group_car_rental_agent')
    rental_cin = fields.Char(
        string='Omang Number',
        size=9,
        help='Enter exactly 9 digits.',
        groups='car_rental_management_odoo.group_car_rental_agent')
    rental_passport_number = fields.Char(
        string='Passport Number',
        size=20,
        help='Enter 6 to 20 letters or digits without spaces or punctuation.',
        groups='car_rental_management_odoo.group_car_rental_agent')
    rental_date_of_birth = fields.Date(string='Date of Birth', groups='car_rental_management_odoo.group_car_rental_agent')
    rental_driving_license = fields.Char(
        string='Driving Licence Number',
        size=20,
        help='Enter 6 to 20 letters or digits without spaces or punctuation.',
        groups='car_rental_management_odoo.group_car_rental_agent')
    rental_license_issue_date = fields.Date(string='Licence Date of Issue', groups='car_rental_management_odoo.group_car_rental_agent')
    rental_license_expiry = fields.Date(string='Licence Expiry', groups='car_rental_management_odoo.group_car_rental_agent')
    rental_identity_number = fields.Char(
        compute='_compute_rental_identity_number',
        groups='car_rental_management_odoo.group_car_rental_agent')
    rental_is_underage = fields.Boolean(
        compute='_compute_rental_age',
        groups='car_rental_management_odoo.group_car_rental_agent')
    rental_age = fields.Integer(
        compute='_compute_rental_age',
        groups='car_rental_management_odoo.group_car_rental_agent')
    rental_birth_date_full = fields.Char(
        compute='_compute_rental_full_dates',
        groups='car_rental_management_odoo.group_car_rental_agent')
    rental_license_issue_date_full = fields.Char(
        compute='_compute_rental_full_dates',
        groups='car_rental_management_odoo.group_car_rental_agent')
    rental_license_expiry_full = fields.Char(
        compute='_compute_rental_full_dates',
        groups='car_rental_management_odoo.group_car_rental_agent')
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

    @api.depends('rental_identity_type', 'rental_cin', 'rental_passport_number')
    def _compute_rental_identity_number(self):
        for partner in self:
            partner.rental_identity_number = (
                partner.rental_cin if partner.rental_identity_type == 'omang'
                else partner.rental_passport_number
            )

    @api.depends('rental_date_of_birth')
    def _compute_rental_age(self):
        today = fields.Date.today()
        for partner in self:
            birthday = partner.rental_date_of_birth
            age = (
                today.year - birthday.year
                - ((today.month, today.day) < (birthday.month, birthday.day))
                if birthday else 0
            )
            partner.rental_age = age
            partner.rental_is_underage = bool(birthday and age < 21)

    @api.depends('rental_date_of_birth', 'rental_license_issue_date', 'rental_license_expiry')
    def _compute_rental_full_dates(self):
        for partner in self:
            for field_name, display_name in (
                    ('rental_date_of_birth', 'rental_birth_date_full'),
                    ('rental_license_issue_date', 'rental_license_issue_date_full'),
                    ('rental_license_expiry', 'rental_license_expiry_full')):
                value = partner[field_name]
                partner[display_name] = (
                    format_date(self.env, value, date_format='d MMMM y') if value else False)

    @api.onchange('rental_identity_type')
    def _onchange_rental_identity_type(self):
        for partner in self:
            if partner.rental_identity_type == 'omang':
                partner.rental_passport_number = False
                partner.rental_passport_document_ids = False
            elif partner.rental_identity_type == 'passport':
                partner.rental_cin = False
                partner.rental_omang_document_ids = False

    @api.model
    def _check_rental_number_input_lengths(self, vals):
        for field_name, limit, message in (
                ('rental_cin', 9, _('An Omang number must contain exactly 9 digits.')),
                ('rental_passport_number', 20, _('A passport number must contain 6 to 20 letters or digits, without spaces or punctuation.')),
                ('rental_driving_license', 20, _('A driving licence number must contain 6 to 20 letters or digits, without spaces or punctuation.'))):
            value = vals.get(field_name)
            if value and len(str(value)) > limit:
                raise ValidationError(message)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._check_rental_number_input_lengths(vals)
        return super().create(vals_list)

    def write(self, vals):
        self._check_rental_number_input_lengths(vals)
        return super().write(vals)

    @api.constrains(
        'rental_identity_type', 'rental_cin', 'rental_passport_number',
        'rental_driving_license')
    def _check_rental_identity_numbers(self):
        alpha_numeric = re.compile(r'^[A-Za-z0-9]{6,20}$')
        for partner in self:
            if partner.rental_cin and not re.fullmatch(r'\d{9}', partner.rental_cin):
                raise ValidationError(_('An Omang number must contain exactly 9 digits.'))
            if partner.rental_passport_number and not alpha_numeric.fullmatch(partner.rental_passport_number):
                raise ValidationError(_('A passport number must contain 6 to 20 letters or digits, without spaces or punctuation.'))
            if partner.rental_driving_license and not alpha_numeric.fullmatch(partner.rental_driving_license):
                raise ValidationError(_('A driving licence number must contain 6 to 20 letters or digits, without spaces or punctuation.'))
            if partner.rental_enabled:
                selected_number = (
                    partner.rental_cin if partner.rental_identity_type == 'omang'
                    else partner.rental_passport_number
                )
                if not selected_number:
                    raise ValidationError(_('Enter the number for the selected identity document.'))
                other_number = (
                    partner.rental_passport_number if partner.rental_identity_type == 'omang'
                    else partner.rental_cin
                )
                if other_number:
                    raise ValidationError(_('Enter only the number for the selected identity document.'))

    @api.constrains(
        'rental_enabled', 'rental_date_of_birth', 'rental_license_issue_date', 'rental_license_expiry')
    def _check_rental_profile_dates(self):
        today = fields.Date.today()
        for partner in self:
            if partner.rental_date_of_birth and partner.rental_date_of_birth >= today:
                raise ValidationError(_('Date of birth must be in the past.'))
            if partner.rental_license_issue_date and partner.rental_license_expiry and partner.rental_license_issue_date > partner.rental_license_expiry:
                raise ValidationError(_('Licence expiry must follow its issue date.'))
            if partner.rental_license_issue_date and partner.rental_license_issue_date > today:
                raise ValidationError(_('Licence date of issue cannot be in the future.'))
            if partner.rental_enabled:
                if partner.rental_date_of_birth:
                    if partner.rental_age < 21:
                        raise ValidationError(_('A rental customer must be at least 21 years old to enable rentals.'))
                if partner.rental_license_expiry and partner.rental_license_expiry < today:
                    raise ValidationError(_('The driving licence has expired. Update the licence details before enabling rentals.'))

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
        identity_documents = (
            self.rental_omang_document_ids if self.rental_identity_type == 'omang'
            else self.rental_passport_document_ids
        )
        if not identity_documents or not self.rental_license_document_ids:
            raise ValidationError(_('Upload either Omang or passport, plus the driving licence, before confirming the reservation.'))

    @api.constrains(
        'rental_enabled', 'street', 'rental_postal_address', 'rental_identity_type',
        'rental_cin', 'rental_passport_number', 'rental_date_of_birth',
        'rental_driving_license', 'rental_license_issue_date', 'rental_license_expiry',
        'rental_omang_document_ids', 'rental_passport_document_ids',
        'rental_license_document_ids')
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
        identity_number = (
            self.rental_cin if self.rental_identity_type == 'omang'
            else self.rental_passport_number
        )
        if not identity_number or any(not self[f] for f in required[1:]):
            raise ValidationError(_('Complete the ID number, date of birth, licence number, issue date and expiry on the Contact.'))
        if self.rental_identity_type == 'omang' and self.rental_passport_number:
            raise ValidationError(_('Clear the passport number when Omang is selected.'))
        if self.rental_identity_type == 'passport' and self.rental_cin:
            raise ValidationError(_('Clear the Omang number when Passport is selected.'))
        identity_documents = (
            self.rental_omang_document_ids if self.rental_identity_type == 'omang'
            else self.rental_passport_document_ids
        )
        if not identity_documents or not self.rental_license_document_ids:
            raise ValidationError(_('Upload the selected Omang or passport document and the driving licence before enabling rentals.'))
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
