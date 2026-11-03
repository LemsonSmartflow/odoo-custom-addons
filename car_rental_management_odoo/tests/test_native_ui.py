"""Native Contacts and Fleet screens backed by the extended standard models.

Rental identity lives directly on res.partner and rental operations directly on
fleet.vehicle, so these tests exercise the public screen actions and the native
record rather than any bespoke bridge model.
"""
from datetime import timedelta
from xml.etree import ElementTree

from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import Form, tagged

from .common import RentalTestCommon


@tagged('post_install', '-at_install')
class TestNativeScreens(RentalTestCommon):

    def test_contact_edits_same_rental_details(self):
        partner = self._make_partner()
        self.assertTrue(partner.rental_enabled)
        partner.write({'rental_cin': 'UPDATED-ID'})
        self.assertEqual(partner.rental_cin, 'UPDATED-ID')
        profile = partner.action_rental_profile()
        self.assertEqual(profile['res_model'], 'res.partner')
        self.assertEqual(profile['res_id'], partner.id)
        self.assertEqual(partner.get_formview_action()['res_model'], 'res.partner')

    def test_native_contact_create_and_booking(self):
        contact = self.env['res.partner'].create({
            'name': 'Native Customer',
            'company_type': 'person',
            'street': 'Physical address',
            'rental_postal_address': 'Postal address',
            'rental_enabled': True,
            'rental_cin': 'NATIVE-ID',
            'rental_date_of_birth': fields.Date.today() - timedelta(days=365 * 30),
            'rental_driving_license': 'NATIVE-LICENCE',
            'rental_license_issue_date': fields.Date.today() - timedelta(days=365 * 3),
            'rental_license_expiry': fields.Date.today() + timedelta(days=365 * 2),
        })
        self.assertTrue(contact.rental_enabled)
        booking = contact.action_rental_book()
        self.assertEqual(booking['res_model'], 'car.rental.journey')
        self.assertEqual(booking['context']['default_partner_id'], contact.id)
        journey = self.env['car.rental.journey'].create({'contact_id': contact.id})
        self.assertEqual(journey.partner_id, contact)
        self.assertEqual(journey.contact_id, contact)
        self.assertEqual(journey.action_customer()['res_model'], 'res.partner')
        self.assertEqual(journey.action_customer()['res_id'], contact.id)

    def test_contact_company_and_incomplete_validation(self):
        ordinary = self.env['res.partner'].create({'name': 'Ordinary Contact'})
        self.assertFalse(ordinary.rental_enabled)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            ordinary.action_rental_book()

        reservation = self._make_reservation()
        as_manager = self.env['car.rental.reservation'].with_user(self.user_manager)
        self.assertEqual(as_manager.search([('id', '=', reservation.id)]).ids, reservation.ids)
        other = self.env['res.company'].create({'name': 'Different rental company'})
        self.user_manager.company_ids = [(4, other.id)]
        self.assertFalse(as_manager.with_context(allowed_company_ids=other.ids).search([('id', '=', reservation.id)]))

    def test_native_fleet_details_keep_one_vehicle(self):
        vehicle = self._make_vehicle(status='setup')
        self.assertEqual(vehicle.action_rental_profile()['res_model'], 'fleet.vehicle')
        before = self.env['fleet.vehicle'].search_count([('company_id', '=', self.company.id)])
        action = vehicle.action_enable_rentals()
        self.assertEqual(action['res_model'], 'fleet.vehicle')
        self.assertEqual(vehicle.rental_status, 'available')
        self.assertEqual(
            self.env['fleet.vehicle'].search_count([('company_id', '=', self.company.id)]), before)
        self.assertEqual(vehicle.get_formview_action()['res_model'], 'fleet.vehicle')
        self.assertEqual(
            vehicle.action_rental_reservations()['res_model'], 'car.rental.reservation')
        self.assertEqual(vehicle.action_rental_rentals()['res_model'], 'car.rental.rental')
        self.assertEqual(vehicle.action_rental_book()['res_model'], 'car.rental.journey')

    def test_native_fleet_activate_requires_registration_and_category(self):
        arch = ElementTree.fromstring(
            self.env['fleet.vehicle'].with_user(self.user_fleet).get_view(view_type='form')['arch'])
        setup_group = arch.find(".//page[@name='rental_details']/group[@name='rental_setup']")
        self.assertIsNotNone(setup_group)
        self.assertEqual(setup_group.get('invisible'), "rental_status != 'setup'")
        self.assertIsNotNone(setup_group.find("./field[@name='rental_category_id']"))

        vehicle = self._make_vehicle(status='setup')
        fresh = self.env['fleet.vehicle'].create({
            'model_id': vehicle.model_id.id,
            'license_plate': 'NATIVE-NEW',
            'company_id': self.company.id,
        })
        with self.assertRaises(ValidationError), self.cr.savepoint():
            fresh.action_enable_rentals()
        fresh.rental_category_id = vehicle.rental_category_id
        fresh.action_rental_activate()
        self.assertEqual(fresh.rental_status, 'available')

    def test_native_menus(self):
        for menu, model in [('menu_car_rental_customer', 'res.partner'),
                            ('menu_car_rental_vehicle', 'fleet.vehicle')]:
            self.assertEqual(
                self.env.ref('car_rental_management_odoo.' + menu).action.res_model, model)

    def test_contact_form_enables_rentals(self):
        agent_group = self.env.ref('car_rental_management_odoo.group_car_rental_agent')
        self.env.user.write({'group_ids': [fields.Command.link(agent_group.id)]})
        with Form(self.env['res.partner']) as ordinary:
            ordinary.name = 'Non-rental Contact'
        self.assertFalse(ordinary.record.rental_enabled)
        with Form(self.env['res.partner']) as form:
            form.name = 'Contact Form Customer'
            form.street = '10 Main Street'
            form.rental_enabled = True
            form.rental_postal_address = 'PO Box 10'
            form.rental_cin = 'FORM-ID'
            form.rental_date_of_birth = fields.Date.today() - timedelta(days=365 * 30)
            form.rental_driving_license = 'FORM-LICENCE'
            form.rental_license_issue_date = fields.Date.today() - timedelta(days=365 * 3)
            form.rental_license_expiry = fields.Date.today() + timedelta(days=365 * 2)
        self.assertTrue(form.record.rental_enabled)
        self.assertEqual(form.record.rental_cin, 'FORM-ID')

    def test_staff_can_read_fleet_without_managing_it(self):
        vehicle = self._make_vehicle()
        staff_vehicle = vehicle.with_user(self.user_agent)
        data = staff_vehicle.read(['license_plate', 'model_id', 'rental_status'])[0]
        self.assertEqual(data['license_plate'], vehicle.license_plate)
        with self.assertRaises(AccessError), self.cr.savepoint():
            staff_vehicle.write({'license_plate': 'NOT-ALLOWED'})
        partner = self._make_partner()
        with Form(partner.with_user(self.user_agent)) as form:
            form.rental_cin = 'STAFF-EDIT'
        self.assertEqual(partner.rental_cin, 'STAFF-EDIT')

    def test_native_receipts_and_category_actions(self):
        from odoo.tools.safe_eval import safe_eval
        action = self.env.ref('car_rental_management_odoo.action_car_rental_payment')
        self.assertEqual(action.res_model, 'account.payment')
        self.assertEqual(self.env.ref('car_rental_management_odoo.menu_car_rental_payment').action, action)
        for xmlid in ('action_car_rental_payment', 'action_categories'):
            action = self.env.ref('car_rental_management_odoo.' + xmlid)
            domain = safe_eval(action.domain or '[]', {'allowed_company_ids': self.company.ids})
            self.env[action.res_model].search(domain, limit=1)
        self.assertIn(('car_rental_id', '!=', False), safe_eval(
            self.env.ref('car_rental_management_odoo.action_car_rental_payment').domain,
            {'allowed_company_ids': self.company.ids}))
