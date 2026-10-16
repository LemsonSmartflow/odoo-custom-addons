from odoo.exceptions import AccessError, ValidationError
from odoo.tests import Form
from odoo import fields
from .test_workflow import TestConnectedWorkflow


class TestNativeScreens(TestConnectedWorkflow):
    def test_contact_edits_same_rental_details(self):
        contact = self.customer.partner_id
        self.assertTrue(contact.rental_enabled)
        self.assertEqual(contact.rental_cin, self.customer.cin)
        contact.write({'rental_cin': 'UPDATED-ID'})
        self.assertEqual(self.customer.cin, 'UPDATED-ID')
        self.assertEqual(contact.action_rental_profile()['res_model'], 'res.partner')
        self.assertEqual(self.customer.get_formview_action()['res_model'], 'res.partner')

    def test_native_contact_create_and_booking(self):
        vals = {'name': 'Native Customer', 'street': 'Physical address', 'rental_postal_address': 'Postal address', 'rental_enabled': True}
        for key in ('cin', 'date_of_birth', 'driving_license', 'license_issue_date', 'license_expiry'):
            vals['rental_' + key] = self.customer[key]
        contact = self.env['res.partner'].create(vals)
        profile = contact._rental_customer()
        self.assertEqual(profile.partner_id, contact)
        journey = self.env['car.rental.journey'].create({'contact_id': contact.id})
        self.assertEqual(journey.customer_id, profile)
        self.assertEqual(journey.action_customer()['res_model'], 'res.partner')
        self.assertEqual(contact.action_rental_book()['context']['default_customer_id'], profile.id)
        self.assertEqual(self.env['car.rental.customer'].search_count([('partner_id', '=', contact.id)]), 1)

    def test_contact_company_and_incomplete_validation(self):
        contact = self.env['res.partner'].create({'name': 'Ordinary Contact'})
        self.assertFalse(contact.rental_enabled)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['car.rental.journey'].create({'contact_id': contact.id})
        other = self.env['res.company'].create({'name': 'Different rental company'})
        self.assertFalse(self.customer.partner_id.with_company(other).rental_enabled)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.customer.partner_id.with_company(other)._rental_customer()

    def test_native_fleet_details_keep_one_vehicle(self):
        fleet = self.vehicle.fleet_vehicle_id
        self.assertEqual(fleet.rental_vehicle_id, self.vehicle)
        self.assertEqual(fleet.action_rental_profile()['res_model'], 'fleet.vehicle')
        fleet.write({'rental_road_license_number': 'ROAD-123'})
        self.assertEqual(self.vehicle.road_license_number, 'ROAD-123')
        fleet.action_enable_rentals()
        self.assertEqual(len(fleet.rental_vehicle_ids), 1)
        self.assertEqual(self.vehicle.get_formview_action()['res_model'], 'fleet.vehicle')
        new = self.env['fleet.vehicle'].create({'model_id': fleet.model_id.id, 'license_plate': 'NATIVE-NEW', 'company_id': self.env.company.id})
        new.action_enable_rentals()
        self.assertEqual(new.rental_status, 'setup')
        new.rental_category_id = self.category
        new.action_rental_activate()
        self.assertEqual(new.rental_status, 'available')

    def test_native_menus(self):
        for menu, model in [('menu_car_rental_customer', 'res.partner'), ('menu_car_rental_vehicle', 'fleet.vehicle')]:
            self.assertEqual(self.env.ref('car_rental_management_odoo.' + menu).action.res_model, model)

    def test_contact_form_enables_rentals(self):
        self.env.user.write({'group_ids': [fields.Command.link(self.env.ref('car_rental_management_odoo.group_car_rental_agent').id)]})
        with Form(self.env['res.partner']) as ordinary:
            ordinary.name = 'Non-rental Contact'
        self.assertFalse(ordinary.record.rental_enabled)
        with Form(self.env['res.partner']) as form:
            form.name = 'Contact Form Customer'
            form.street = '10 Main Street'
            form.rental_enabled = True
            form.rental_postal_address = 'PO Box 10'
            form.rental_cin = 'FORM-ID'
            form.rental_date_of_birth = self.customer.date_of_birth
            form.rental_driving_license = 'FORM-LICENCE'
            form.rental_license_issue_date = self.customer.license_issue_date
            form.rental_license_expiry = self.customer.license_expiry
        self.assertTrue(form.record.rental_enabled)
        self.assertEqual(form.record._rental_customer().cin, 'FORM-ID')

    def test_staff_can_read_fleet_without_managing_it(self):
        staff = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Native Screen Staff', 'login': 'native-screen-staff',
            'company_id': self.env.company.id, 'company_ids': [fields.Command.set(self.env.company.ids)],
            'group_ids': [fields.Command.set([self.env.ref('base.group_user').id, self.env.ref('car_rental_management_odoo.group_car_rental_agent').id])]})
        fleet = self.vehicle.fleet_vehicle_id.with_user(staff)
        self.assertEqual(fleet.read(['license_plate', 'model_id', 'rental_status'])[0]['license_plate'], self.vehicle.registration_number)
        with self.assertRaises(AccessError), self.cr.savepoint():
            fleet.write({'license_plate': 'NOT-ALLOWED'})
        with Form(self.customer.partner_id.with_user(staff)) as form:
            form.rental_cin = 'STAFF-EDIT'
        self.assertEqual(self.customer.cin, 'STAFF-EDIT')
