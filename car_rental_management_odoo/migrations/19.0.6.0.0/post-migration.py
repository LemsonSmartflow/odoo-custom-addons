from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    from odoo.addons.car_rental_management_odoo.models.shared_records import Customer, Partner, Vehicle, Fleet, CONTACT_FIELDS, VEHICLE_FIELDS
    customers = env['car.rental.customer'].with_context(active_test=False).search([])
    for customer in customers:
        if not customer.partner_id:
            customer._ensure_partner()
        else:
            partner = customer.partner_id
            missing = {target: customer[key] for key, target in CONTACT_FIELDS.items() if not partner[target] and customer[key]}
            if missing:
                super(Partner, partner).write(missing)
            projected = customer._contact_values(partner)
            # Preserve incomplete historical profiles for correction at the
            # next booking, rather than inventing mandatory address details.
            if not projected['physical_address'] or not projected['postal_address']:
                projected.pop('physical_address', None)
                projected.pop('postal_address', None)
                projected.pop('address', None)
            super(Customer, customer).write(projected)
    for vehicle in env['car.rental.vehicle'].with_context(active_test=False).search([]):
        if vehicle.fleet_vehicle_id:
            fleet = vehicle.fleet_vehicle_id
            missing = {target: vehicle[key] for key, target in VEHICLE_FIELDS.items() if not fleet[target] and vehicle[key]}
            if not fleet.fuel_type and vehicle.fuel_type:
                missing['fuel_type'] = {'petrol': 'gasoline', 'hybrid': 'full_hybrid'}.get(vehicle.fuel_type, vehicle.fuel_type)
            if missing:
                super(Fleet, fleet).write(missing)
            super(Vehicle, vehicle).write(vehicle._fleet_values(vehicle.fleet_vehicle_id))
        elif vehicle.registration_number and vehicle.brand and vehicle.model:
            vehicle.action_sync_fleet()
