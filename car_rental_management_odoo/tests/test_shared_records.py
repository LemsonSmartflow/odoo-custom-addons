from odoo.exceptions import ValidationError
from .test_workflow import TestConnectedWorkflow


class TestSharedRecords(TestConnectedWorkflow):
    def test_contacts_are_authoritative_for_invoice(self):
        partner = self.customer.partner_id
        self.assertTrue(partner)
        partner.write({'name': 'Updated Contact', 'email': 'updated@example.test', 'phone': '12345', 'street': 'New physical address'})
        self.assertEqual(self.customer.first_name, 'Updated')
        self.assertEqual(self.customer.email, partner.email)
        self.assertEqual(self.customer.physical_address, partner.street)
        rental = self.rental()
        rental.action_invoice()
        self.assertEqual(rental.invoice_ids.partner_id, partner)
        self.assertEqual(partner.email, 'updated@example.test')
        self.customer.write({'phone': '67890'})
        self.assertEqual(partner.phone, '67890')

    def test_existing_contact_reused_and_link_protected(self):
        partner = self.env['res.partner'].create({'name': 'Existing Person', 'street': 'Physical address', 'rental_postal_address': 'Postal address', 'email': 'person@example.test'})
        vals = self.customer.copy_data()[0]
        vals.update(partner_id=partner.id, first_name='Stale', email='stale@example.test')
        profile = self.env['car.rental.customer'].create(vals)
        self.assertEqual(profile.partner_id, partner)
        self.assertEqual(profile.first_name, 'Existing')
        self.assertEqual(profile.email, 'person@example.test')
        self.assertEqual(partner.action_rental_profile()['res_id'], profile.id)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            profile.write({'partner_id': self.customer.partner_id.id})

    def test_fleet_shared_both_directions(self):
        fleet = self.vehicle.fleet_vehicle_id
        self.assertTrue(fleet)
        fleet.write({'license_plate': 'SHARED-123', 'color': 'Blue', 'odometer': 1500})
        self.assertEqual(self.vehicle.registration_number, 'SHARED-123')
        self.assertEqual(self.vehicle.fleet_id, 'SHARED-123')
        self.assertEqual(self.vehicle.mileage, 1500)
        self.vehicle.write({'color': 'Red'})
        self.assertEqual(fleet.color, 'Red')
        self.assertEqual(self.vehicle.action_sync_fleet()['res_id'], fleet.id)
        self.assertEqual(fleet.action_rental_profile()['res_id'], self.vehicle.id)
        self.env['fleet.vehicle.odometer'].create({'vehicle_id': fleet.id, 'value': 1700, 'date': '2026-10-16'})
        self.assertEqual(self.vehicle.mileage, 1700)
        fleet.fuel_type = 'gasoline'
        self.assertEqual(self.vehicle.fuel_type, 'petrol')
        self.vehicle.fuel_type = 'diesel'
        self.assertEqual(fleet.fuel_type, 'diesel')

    def test_existing_fleet_reused(self):
        fleet = self.env['fleet.vehicle'].create({'model_id': self.vehicle.fleet_vehicle_id.model_id.id, 'license_plate': 'EXISTING-1', 'company_id': self.env.company.id})
        vehicle = self.env['car.rental.vehicle'].create({'fleet_vehicle_id': fleet.id, 'category_id': self.category.id, 'company_id': self.env.company.id})
        self.assertEqual(vehicle.registration_number, fleet.license_plate)
        self.assertEqual(vehicle.fleet_vehicle_id, fleet)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            vehicle.write({'fleet_vehicle_id': self.vehicle.fleet_vehicle_id.id})
