"""Native Contacts/Fleet screens with company-scoped rental extensions.

Historical rental IDs remain internal links, not a second customer directory.
"""
from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError
from .workflow import window

STAFF = 'car_rental_management_odoo.group_car_rental_agent'
IDENTITY = ('cin', 'date_of_birth', 'driving_license', 'license_issue_date',
            'license_expiry', 'omang_document_ids', 'passport_document_ids',
            'license_document_ids', 'document_ids')


class Partner(models.Model):
    _inherit = 'res.partner'

    rental_customer_ids = fields.One2many('car.rental.customer', 'partner_id', groups=STAFF)
    rental_enabled = fields.Boolean(compute='_compute_rental_details', inverse='_inverse_rental_details', groups=STAFF)
    rental_cin = fields.Char(string='Omang / Passport Number', compute='_compute_rental_details', inverse='_inverse_rental_details', groups=STAFF)
    rental_date_of_birth = fields.Date(string='Date of Birth', compute='_compute_rental_details', inverse='_inverse_rental_details', groups=STAFF)
    rental_driving_license = fields.Char(string='Licence Number', compute='_compute_rental_details', inverse='_inverse_rental_details', groups=STAFF)
    rental_license_issue_date = fields.Date(string='Licence Issue Date', compute='_compute_rental_details', inverse='_inverse_rental_details', groups=STAFF)
    rental_license_expiry = fields.Date(string='Licence Expiry', compute='_compute_rental_details', inverse='_inverse_rental_details', groups=STAFF)
    rental_omang_document_ids = fields.Many2many('ir.attachment', compute='_compute_rental_details', inverse='_inverse_rental_details', string='Omang Documents', groups=STAFF)
    rental_passport_document_ids = fields.Many2many('ir.attachment', compute='_compute_rental_details', inverse='_inverse_rental_details', string='Passport Documents', groups=STAFF)
    rental_license_document_ids = fields.Many2many('ir.attachment', compute='_compute_rental_details', inverse='_inverse_rental_details', string='Licence Documents', groups=STAFF)
    rental_document_ids = fields.Many2many('ir.attachment', compute='_compute_rental_details', inverse='_inverse_rental_details', string='Other / Existing Documents', groups=STAFF)

    @api.depends_context('company')
    @api.depends('rental_customer_ids', *['rental_customer_ids.' + key for key in IDENTITY])
    def _compute_rental_details(self):
        for partner in self:
            profile = partner.rental_customer_ids.filtered(lambda p: p.company_id == self.env.company)[:1]
            partner.rental_enabled = bool(profile)
            for key in IDENTITY:
                partner['rental_' + key] = profile[key] if profile else False

    def _inverse_rental_details(self):
        # create/write persist all submitted rental fields together, so a new
        # customer's required details are validated as a whole.
        pass

    def _rental_customer(self):
        self.ensure_one()
        profile = self.env['car.rental.customer'].search([
            ('partner_id', '=', self.id), ('company_id', '=', self.env.company.id)], limit=1)
        if not profile:
            raise ValidationError('Open this Contact, enable rentals in Rental Details and complete the identity, licence and address fields first.')
        return profile

    def _save_rental_details(self, values):
        if not values:
            return
        if not self.env.su and not self.env.user.has_group(STAFF):
            raise AccessError('Only rental staff can edit rental identity and licence details.')
        for partner in self:
            profiles = self.env['car.rental.customer'].with_context(active_test=False).search([
                ('partner_id', '=', partner.id), ('company_id', '=', self.env.company.id)], limit=1)
            if values.get('rental_enabled') is False and profiles:
                raise ValidationError('Rental details with history cannot be disabled. Archive the contact if it is no longer used.')
            vals = {key: values['rental_' + key] for key in IDENTITY if 'rental_' + key in values}
            if profiles:
                profiles.write(vals)
            elif values.get('rental_enabled', any(vals.get(key) for key in IDENTITY if not key.endswith('_ids'))):
                if not partner.street or not partner.rental_postal_address:
                    raise ValidationError('Enter the physical street address and postal address on the Contact before enabling rentals.')
                required = ('cin', 'date_of_birth', 'driving_license', 'license_issue_date', 'license_expiry')
                if any(not vals.get(key) for key in required):
                    raise ValidationError('Complete the ID number, date of birth, licence number, issue date and expiry in Rental Details.')
                self.env['car.rental.customer'].create(dict(vals, partner_id=partner.id, company_id=self.env.company.id))
            partner.invalidate_recordset(['rental_enabled'] + ['rental_' + key for key in IDENTITY])

    @api.model_create_multi
    def create(self, vals_list):
        keys = {'rental_enabled'} | {'rental_' + key for key in IDENTITY}
        records = super().create([{k: v for k, v in vals.items() if k not in keys} for vals in vals_list])
        for record, vals in zip(records, vals_list):
            record._save_rental_details({k: v for k, v in vals.items() if k in keys})
        return records

    def write(self, vals):
        keys = {'rental_enabled'} | {'rental_' + key for key in IDENTITY}
        result = super().write({k: v for k, v in vals.items() if k not in keys})
        self._save_rental_details({k: v for k, v in vals.items() if k in keys})
        return result

    def action_rental_profile(self):
        self.ensure_one()
        return window('Customer', 'res.partner', res_id=self.id)

    def action_rental_book(self):
        profile = self._rental_customer()
        return dict(window('Create a Booking', 'car.rental.journey', context={
            'default_customer_id': profile.id, 'default_contact_id': self.id,
            'default_company_id': self.env.company.id}), view_mode='form')

    def action_rental_reservations(self):
        self.ensure_one()
        return window('Reservations', 'car.rental.reservation', [('customer_id.partner_id', '=', self.id)])

    def action_rental_rentals(self):
        self.ensure_one()
        return window('Rentals', 'car.rental.rental', [('customer_id.partner_id', '=', self.id)])


class ContactSelection(models.AbstractModel):
    _name = 'car.rental.contact.selection'
    _description = 'Contact selection for rental bookings'

    contact_id = fields.Many2one('res.partner', string='Customer', compute='_compute_contact', inverse='_inverse_contact', search='_search_contact')

    @api.depends('customer_id.partner_id')
    def _compute_contact(self):
        for record in self:
            record.contact_id = record.customer_id.partner_id

    def _inverse_contact(self):
        pass

    def _search_contact(self, operator, value):
        return [('customer_id.partner_id', operator, value)]

    @api.onchange('contact_id')
    def _onchange_native_contact(self):
        if self.contact_id:
            self.customer_id = self.contact_id.with_company(self.company_id or self.env.company)._rental_customer()
        else:
            self.customer_id = False

    def _prepare_contact(self, vals, company):
        vals = dict(vals)
        if 'contact_id' in vals:
            contact = self.env['res.partner'].browse(vals.pop('contact_id'))
            vals['customer_id'] = contact.with_company(company)._rental_customer().id if contact else False
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        return super().create([self._prepare_contact(vals, self.env['res.company'].browse(vals.get('company_id')) or self.env.company) for vals in vals_list])

    def write(self, vals):
        if 'contact_id' not in vals:
            return super().write(vals)
        for record in self:
            prepared = self._prepare_contact(vals, self.env['res.company'].browse(vals.get('company_id')) or record.company_id)
            super(ContactSelection, record).write(prepared)
        return True


class Reservation(models.Model):
    _name = 'car.rental.reservation'
    _inherit = ['car.rental.reservation', 'car.rental.contact.selection']


class Journey(models.Model):
    _name = 'car.rental.journey'
    _inherit = ['car.rental.journey', 'car.rental.contact.selection']

    def action_customer(self):
        self.ensure_one()
        return window('Customer', 'res.partner', res_id=self.contact_id.id)

    def action_vehicle(self):
        self.ensure_one()
        vehicle = self.reservation_id.vehicle_id or self.vehicle_id
        return window('Vehicle', 'fleet.vehicle', res_id=vehicle.fleet_vehicle_id.id)


class Rental(models.Model):
    _inherit = 'car.rental.rental'
    contact_id = fields.Many2one(related='customer_id.partner_id', string='Customer')


class Payment(models.Model):
    _inherit = 'car.rental.payment'
    contact_id = fields.Many2one(related='customer_id.partner_id', string='Customer')


class CustomerLink(models.Model):
    _inherit = 'car.rental.customer'

    def get_formview_action(self, access_uid=None):
        self.ensure_one()
        return self.action_contact()


class VehicleLink(models.Model):
    _inherit = 'car.rental.vehicle'

    def get_formview_action(self, access_uid=None):
        self.ensure_one()
        if self.fleet_vehicle_id:
            return self.action_sync_fleet()
        return super().get_formview_action(access_uid=access_uid)


class Dashboard(models.Model):
    _inherit = 'car.rental.dashboard'

    def action_customers(self):
        return self.env['ir.actions.actions']._for_xml_id('car_rental_management_odoo.action_native_customers')

    def action_vehicles(self):
        return self.env['ir.actions.actions']._for_xml_id('car_rental_management_odoo.action_native_vehicles')

    def action_available(self):
        action = self.action_vehicles()
        ids = self.env['car.rental.vehicle'].search([('company_id', '=', self.env.company.id), ('status', '=', 'available')]).fleet_vehicle_id.ids
        action['domain'] = [('id', 'in', ids)]
        return action

    def action_reserved(self):
        action = self.action_vehicles()
        ids = self.env['car.rental.vehicle'].search([('company_id', '=', self.env.company.id), ('status', '=', 'reserved')]).fleet_vehicle_id.ids
        action['domain'] = [('id', 'in', ids)]
        return action


class Fleet(models.Model):
    _inherit = 'fleet.vehicle'

    rental_vehicle_ids = fields.One2many('car.rental.vehicle', 'fleet_vehicle_id')
    rental_vehicle_id = fields.Many2one('car.rental.vehicle', compute='_compute_rental_vehicle', store=True)
    rental_category_id = fields.Many2one(related='rental_vehicle_id.category_id', readonly=False, string='Rental Category')
    rental_status = fields.Selection(related='rental_vehicle_id.status', string='Rental Availability')
    rental_insurance_provider = fields.Char(related='rental_vehicle_id.insurance_provider', readonly=False)
    rental_insurance_policy = fields.Char(related='rental_vehicle_id.insurance_policy', readonly=False)
    rental_insurance_expiry = fields.Date(related='rental_vehicle_id.insurance_expiry', readonly=False)
    rental_road_license_number = fields.Char(related='rental_vehicle_id.road_license_number', readonly=False)
    rental_road_license_expiry = fields.Date(related='rental_vehicle_id.road_license_expiry', readonly=False)
    rental_tracker_working = fields.Boolean(related='rental_vehicle_id.tracker_working', readonly=False)
    rental_next_service_date = fields.Date(related='rental_vehicle_id.next_service_date', readonly=False)
    rental_next_service_mileage = fields.Float(related='rental_vehicle_id.next_service_mileage', readonly=False)
    rental_document_ids = fields.Many2many(related='rental_vehicle_id.document_ids', readonly=False)
    rental_image = fields.Image(related='rental_vehicle_id.image_1920', readonly=False, string='Rental Preview')

    @api.depends('rental_vehicle_ids')
    def _compute_rental_vehicle(self):
        for fleet in self:
            fleet.rental_vehicle_id = fleet.rental_vehicle_ids[:1]

    def action_enable_rentals(self):
        self.ensure_one()
        if not self.rental_vehicle_id:
            if not self.license_plate or not self.model_id:
                raise ValidationError('Enter the registration plate and vehicle model first.')
            self.env['car.rental.vehicle'].create({'fleet_vehicle_id': self.id, 'company_id': self.company_id.id, 'status': 'setup'})
        return window('Vehicle', 'fleet.vehicle', res_id=self.id)

    def action_rental_profile(self):
        self.ensure_one()
        return window('Vehicle', 'fleet.vehicle', res_id=self.id)

    def action_rental_reservations(self):
        return self.rental_vehicle_id.action_reservations()

    def action_rental_rentals(self):
        return self.rental_vehicle_id.action_rentals()

    def action_rental_release(self):
        return self.rental_vehicle_id.action_release()

    def action_rental_activate(self):
        return self.rental_vehicle_id.action_activate()

    def action_rental_cleaning(self):
        return self.rental_vehicle_id.action_mark_cleaning()

    def action_rental_maintenance(self):
        return self.rental_vehicle_id.action_maintenance()

    def action_rental_book(self):
        return self.rental_vehicle_id.action_book()
