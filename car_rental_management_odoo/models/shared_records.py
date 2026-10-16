"""Rental eligibility and availability extend shared Contacts and Fleet records.

Existing rental IDs remain stable. Shared columns on rental profiles are projections,
not a second source to overwrite Contacts or Fleet during invoicing/handover.
"""
from odoo import api, fields, models
from odoo.exceptions import ValidationError
from .workflow import window
from odoo.addons.fleet.models.fleet_vehicle_model import FUEL_TYPES


CONTACT_FIELDS = {'phone': 'phone', 'email': 'email', 'physical_address': 'street',
                  'postal_address': 'rental_postal_address'}
VEHICLE_FIELDS = {'registration_number': 'license_plate', 'vin': 'vin_sn',
                  'color': 'color', 'seats': 'seats', 'transmission': 'transmission'}


class Customer(models.Model):
    _inherit = 'car.rental.customer'
    _contact_company_unique = models.Constraint('UNIQUE(partner_id, company_id)', 'This contact already has a rental profile in this company.')

    last_name = fields.Char(required=False)

    def _contact_values(self, partner):
        partner.check_access('read')
        first, _, last = (partner.name or '').partition(' ')
        return dict({key: partner[target] for key, target in CONTACT_FIELDS.items()},
                    first_name=first, last_name=last, address=partner.street)

    @api.onchange('partner_id')
    def _onchange_contact(self):
        if self.partner_id:
            self.update(self._contact_values(self.partner_id))

    @api.constrains('partner_id', 'company_id')
    def _check_shared_contact(self):
        for customer in self:
            partner = customer.partner_id
            if partner.company_id and partner.company_id != customer.company_id:
                raise ValidationError('Choose a shared contact or a contact belonging to this rental company.')
            if partner and self.sudo().with_context(active_test=False).search_count([('partner_id', '=', partner.id), ('company_id', '=', customer.company_id.id), ('id', '!=', customer.id)]):
                raise ValidationError('This contact already has a rental customer profile in this company. Open that profile instead.')

    @api.model_create_multi
    def create(self, vals_list):
        prepared = []
        for vals in vals_list:
            vals = dict(vals)
            if vals.get('partner_id'):
                partner = self.env['res.partner'].browse(vals['partner_id'])
                # A selected contact is authoritative. Rental-specific missing
                # postal/address details may be entered while enabling rentals.
                shared = self._contact_values(partner)
                vals.update({k: v for k, v in shared.items() if v or not vals.get(k)})
            prepared.append(vals)
        records = super().create(prepared)
        for record in records:
            record._ensure_partner()
        return records

    def _ensure_partner(self):
        for customer in self:
            if not customer.partner_id:
                partner = self.env['res.partner'].create(dict(
                    {target: customer[key] for key, target in CONTACT_FIELDS.items()},
                    name=customer.display_name, company_id=customer.company_id.id))
                super(Customer, customer).write({'partner_id': partner.id})
            else:
                # Fill missing contact addresses once; never overwrite a newer
                # Contacts value with the rental copy when raising an invoice.
                missing = {target: customer[key] for key, target in CONTACT_FIELDS.items()
                           if not customer.partner_id[target] and customer[key]}
                if missing:
                    customer.partner_id.write(missing)
        return self.partner_id

    def write(self, vals):
        if 'partner_id' in vals and any(c.partner_id and c.partner_id.id != vals['partner_id'] for c in self):
            raise ValidationError('The shared contact cannot be replaced after linking. Edit the contact or create a different rental customer.')
        result = super().write(vals)
        for customer in self:
            if customer.partner_id:
                shared = {target: vals[key] for key, target in CONTACT_FIELDS.items() if key in vals}
                if {'first_name', 'last_name'} & vals.keys():
                    shared['name'] = ' '.join(filter(None, [customer.first_name, customer.last_name]))
                if shared:
                    customer.partner_id.write(shared)
        return result

    def action_contact(self):
        self.ensure_one()
        return window('Contact', 'res.partner', res_id=self._ensure_partner().id)


class Partner(models.Model):
    _inherit = 'res.partner'

    rental_postal_address = fields.Text(string='Rental Postal Address')

    def write(self, vals):
        if vals.get('company_id'):
            profiles = self.env['car.rental.customer'].sudo().with_context(active_test=False).search([('partner_id', 'in', self.ids)])
            if any(p.company_id.id != vals['company_id'] for p in profiles):
                raise ValidationError('This contact is linked to rental profiles in another company. Keep it shared.')
        result = super().write(vals)
        if set(CONTACT_FIELDS.values()).union({'name'}) & vals.keys():
            profiles = self.env['car.rental.customer'].sudo().with_context(active_test=False).search([('partner_id', 'in', self.ids)])
            for profile in profiles:
                projected = {key: profile.partner_id[target] for key, target in CONTACT_FIELDS.items() if target in vals}
                if 'name' in vals:
                    first, _, last = (profile.partner_id.name or '').partition(' ')
                    projected.update(first_name=first, last_name=last)
                # Bypass only the outbound synchronization, preserving all
                # rental eligibility constraints and normal model extensions.
                super(Customer, profile).write(projected)
        return result

    def action_rental_profile(self):
        self.ensure_one()
        profile = self.env['car.rental.customer'].search([('partner_id', '=', self.id), ('company_id', '=', self.env.company.id)], limit=1)
        if profile:
            return window('Rental Customer', profile._name, res_id=profile.id)
        return dict(window('Enable Customer Rentals', 'car.rental.customer', context={
            'default_partner_id': self.id, **{'default_' + k: v for k, v in self.env['car.rental.customer']._contact_values(self).items()}}), view_mode='form')


class Vehicle(models.Model):
    _inherit = 'car.rental.vehicle'
    _shared_fleet_unique = models.Constraint('UNIQUE(fleet_vehicle_id)', 'This Fleet vehicle already has a rental profile.')

    fleet_vehicle_id = fields.Many2one('fleet.vehicle', string='Fleet Vehicle', readonly=False, copy=False, ondelete='restrict', check_company=True)
    fuel_type = fields.Selection(selection_add=[item for item in FUEL_TYPES if item[0] not in ('diesel', 'electric')], ondelete={item[0]: 'set null' for item in FUEL_TYPES if item[0] not in ('diesel', 'electric')})

    def _fleet_values(self, fleet):
        fleet.check_access('read')
        return dict({key: fleet[target] for key, target in VEHICLE_FIELDS.items()},
                    brand=fleet.model_id.brand_id.name, model=fleet.model_id.name,
                    fleet_id=fleet.license_plate, mileage=fleet.odometer,
                    fuel_type={'gasoline': 'petrol', 'full_hybrid': 'hybrid'}.get(fleet.fuel_type, fleet.fuel_type))

    @api.onchange('fleet_vehicle_id')
    def _onchange_shared_fleet(self):
        if self.fleet_vehicle_id:
            self.update(self._fleet_values(self.fleet_vehicle_id))

    @api.constrains('fleet_vehicle_id', 'company_id')
    def _check_shared_fleet(self):
        for vehicle in self:
            fleet = vehicle.fleet_vehicle_id
            if fleet and fleet.company_id != vehicle.company_id:
                raise ValidationError('Fleet vehicle and rental profile must belong to the same company.')
            if fleet and self.sudo().with_context(active_test=False).search_count([('fleet_vehicle_id', '=', fleet.id), ('id', '!=', vehicle.id)]):
                raise ValidationError('This Fleet vehicle already has a rental profile.')

    @api.model_create_multi
    def create(self, vals_list):
        prepared = []
        for vals in vals_list:
            vals = dict(vals)
            if vals.get('fleet_vehicle_id'):
                vals.update(self._fleet_values(self.env['fleet.vehicle'].browse(vals['fleet_vehicle_id'])))
            prepared.append(vals)
        records = super().create(prepared)
        for record in records:
            if not record.fleet_vehicle_id and record.registration_number and record.brand and record.model:
                record.action_sync_fleet()
        return records

    def write(self, vals):
        if 'fleet_vehicle_id' in vals and any(v.fleet_vehicle_id and v.fleet_vehicle_id.id != vals['fleet_vehicle_id'] for v in self):
            raise ValidationError('A linked Fleet vehicle cannot be replaced. Open Fleet to edit its details.')
        linking = vals.get('fleet_vehicle_id') and not any(self.mapped('fleet_vehicle_id'))
        if linking:
            vals = dict(vals, **self._fleet_values(self.env['fleet.vehicle'].browse(vals['fleet_vehicle_id'])))
        if {'brand', 'model'} & vals.keys() and any(self.mapped('fleet_vehicle_id')):
            raise ValidationError('Change the vehicle model in Fleet; its rental profile updates automatically.')
        result = super().write(vals)
        if linking:
            return result
        for vehicle in self:
            if vehicle.fleet_vehicle_id:
                shared = {target: vehicle[key] for key, target in VEHICLE_FIELDS.items() if key in vals}
                if 'fleet_id' in vals:
                    shared['license_plate'] = vehicle.registration_number
                if 'mileage' in vals:
                    shared['odometer'] = vehicle.mileage
                if 'fuel_type' in vals:
                    shared['fuel_type'] = {'petrol': 'gasoline', 'hybrid': 'full_hybrid'}.get(vehicle.fuel_type, vehicle.fuel_type)
                if shared:
                    vehicle.fleet_vehicle_id.write(shared)
            elif vehicle.registration_number and vehicle.brand and vehicle.model:
                vehicle.action_sync_fleet()
        return result

    def action_sync_fleet(self):
        self.ensure_one()
        if self.fleet_vehicle_id:
            return window('Fleet Vehicle', 'fleet.vehicle', res_id=self.fleet_vehicle_id.id)
        # Existing Fleet records are selected explicitly, not guessed from a
        # registration string that may have been reused or entered incorrectly.
        fuel, transmission = self.fuel_type, self.transmission
        result = super().action_sync_fleet()
        self.fleet_vehicle_id.write({'fuel_type': {'petrol': 'gasoline', 'hybrid': 'full_hybrid'}.get(fuel, fuel), 'transmission': transmission})
        return result


class Fleet(models.Model):
    _inherit = 'fleet.vehicle'

    def write(self, vals):
        if 'company_id' in vals:
            profiles = self.env['car.rental.vehicle'].sudo().with_context(active_test=False).search([('fleet_vehicle_id', 'in', self.ids)])
            if any(p.company_id.id != vals['company_id'] for p in profiles):
                raise ValidationError('A vehicle with rental history cannot be moved to another company.')
        result = super().write(vals)
        if set(VEHICLE_FIELDS.values()).union({'model_id', 'odometer', 'fuel_type'}) & vals.keys():
            profiles = self.env['car.rental.vehicle'].sudo().with_context(active_test=False).search([('fleet_vehicle_id', 'in', self.ids)])
            for profile in profiles:
                fleet = profile.fleet_vehicle_id
                projected = {key: fleet[target] for key, target in VEHICLE_FIELDS.items() if target in vals}
                if 'model_id' in vals:
                    projected.update(profile._fleet_values(fleet))
                if 'odometer' in vals:
                    projected['mileage'] = fleet.odometer
                if 'fuel_type' in vals:
                    projected['fuel_type'] = {'gasoline': 'petrol', 'full_hybrid': 'hybrid'}.get(fleet.fuel_type, fleet.fuel_type)
                super(Vehicle, profile).write(projected)
        return result

    def action_rental_profile(self):
        self.ensure_one()
        profile = self.env['car.rental.vehicle'].search([('fleet_vehicle_id', '=', self.id)], limit=1)
        if profile:
            return window('Rental Vehicle', profile._name, res_id=profile.id)
        return dict(window('Enable Vehicle Rentals', 'car.rental.vehicle', context={
            'default_fleet_vehicle_id': self.id, 'default_company_id': self.company_id.id,
            **{'default_' + k: v for k, v in self.env['car.rental.vehicle']._fleet_values(self).items()}}), view_mode='form')


class Odometer(models.Model):
    _inherit = 'fleet.vehicle.odometer'

    def _update_rental_mileage(self, vehicles):
        vehicles.invalidate_recordset(['odometer'])
        for profile in self.env['car.rental.vehicle'].sudo().with_context(active_test=False).search([('fleet_vehicle_id', 'in', vehicles.ids)]):
            # During Fleet's odometer inverse the computed field is protected;
            # reading it there yields False. Use the same maximum log as Fleet.
            latest = self.sudo().search([('vehicle_id', '=', profile.fleet_vehicle_id.id)], order='value desc', limit=1)
            super(Vehicle, profile).write({'mileage': latest.value if latest else 0})

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._update_rental_mileage(records.vehicle_id)
        return records

    def write(self, vals):
        vehicles = self.vehicle_id
        result = super().write(vals)
        self._update_rental_mileage(vehicles | self.vehicle_id)
        return result

    def unlink(self):
        vehicles = self.vehicle_id
        result = super().unlink()
        self._update_rental_mileage(vehicles)
        return result


class FleetModel(models.Model):
    _inherit = 'fleet.vehicle.model'

    def write(self, vals):
        result = super().write(vals)
        if {'name', 'brand_id'} & vals.keys():
            profiles = self.env['car.rental.vehicle'].sudo().with_context(active_test=False).search([('fleet_vehicle_id.model_id', 'in', self.ids)])
            for profile in profiles:
                super(Vehicle, profile).write({'brand': profile.fleet_vehicle_id.model_id.brand_id.name, 'model': profile.fleet_vehicle_id.model_id.name})
        return result

