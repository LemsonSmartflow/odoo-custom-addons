from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    # Remove only unused original placeholders; edited/used vehicles retain history.
    records = env['ir.model.data'].search([
        ('module', '=', 'car_rental_management_odoo'),
        ('model', '=', 'car.rental.vehicle'), ('name', '=like', 'demio_setup_%'),
    ])
    for ref in records:
        vehicle = env['car.rental.vehicle'].browse(ref.res_id).exists()
        if vehicle and vehicle.write_date == vehicle.create_date and vehicle.brand == 'Mazda' and vehicle.model == 'Demio' and not vehicle.vin and not vehicle.image_1920 and not vehicle.document_ids and vehicle.status == 'setup' and not vehicle.registration_number and not vehicle.mileage and not vehicle.reservation_ids and not vehicle.rental_ids and not vehicle.fleet_vehicle_id and not vehicle.equipment_id:
            vehicle.unlink()
            ref.unlink()
    for ref in env['ir.model.data'].search([('module', '=', 'car_rental_management_odoo'), ('model', '=', 'car.rental.rate.rule'), ('name', '=like', 'example_rate_%')]):
        rule = env['car.rental.rate.rule'].browse(ref.res_id).exists()
        if rule and rule.state == 'draft' and (rule.name or '').startswith('EXAMPLE ONLY') and not env['car.rental.reservation'].search_count([('pricing_rule_id', '=', rule.id)]):
            rule.unlink()
            ref.unlink()
    # Existing actual registrations become the shared ID; never rewrite bookings/references.
    vehicles = env['car.rental.vehicle'].search([('registration_number', '!=', False)])
    for vehicle in vehicles:
        vehicle.fleet_id = vehicle.registration_number
    # Carry the known old physical address forward, without inventing personal details.
    for customer in env['car.rental.customer'].search([('physical_address', '=', False), ('address', '!=', False)]):
        cr.execute('UPDATE car_rental_customer SET physical_address = %s WHERE id = %s', [customer.address, customer.id])
