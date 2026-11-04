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
        partner.write({'rental_cin': '987654321'})
        self.assertEqual(partner.rental_cin, '987654321')
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
            'rental_identity_type': 'omang',
            'rental_cin': '123456789',
            'rental_date_of_birth': fields.Date.today() - timedelta(days=365 * 30),
            'rental_driving_license': '12345678901234',
            'rental_license_issue_date': fields.Date.today() - timedelta(days=365 * 3),
            'rental_license_expiry': fields.Date.today() + timedelta(days=365 * 2),
            'rental_omang_document_ids': [(6, 0, [self._attachment('native-omang.png').id])],
            'rental_license_document_ids': [(6, 0, [self._attachment('native-licence.png').id])],
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
        self.assertEqual(vehicle.rental_category_id, vehicle.category_id)
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

        brand = self.env['fleet.vehicle.model.brand'].create({'name': 'Uncategorized Brand'})
        model = self.env['fleet.vehicle.model'].create({
            'name': 'Uncategorized Model', 'brand_id': brand.id,
            'vehicle_type': 'car'})
        fresh = self.env['fleet.vehicle'].create({
            'model_id': model.id,
            'license_plate': 'NATIVE-NEW',
            'company_id': self.company.id,
        })
        with self.assertRaises(ValidationError), self.cr.savepoint():
            fresh.action_enable_rentals()
        fresh.category_id = self._make_category()
        self.assertEqual(fresh.rental_category_id, fresh.category_id)
        fresh.action_rental_activate()
        self.assertEqual(fresh.rental_status, 'available')

    def test_native_menus(self):
        for menu, model in [('menu_car_rental_customer', 'res.partner'),
                            ('menu_car_rental_vehicle', 'fleet.vehicle')]:
            self.assertEqual(
                self.env.ref('car_rental_management_odoo.' + menu).action.res_model, model)

    def test_customer_and_vehicle_lists_expose_date_and_type_sorting(self):
        contact_list = self.env['res.partner'].get_view(view_type='list')['arch']
        fleet_list = self.env['fleet.vehicle'].get_view(view_type='list')['arch']
        fleet_form = self.env['fleet.vehicle'].get_view(view_type='form')['arch']
        contact_form = self.env['res.partner'].with_user(
            self.user_agent).get_view(view_type='form')['arch']
        fleet_search = self.env['fleet.vehicle'].get_view(view_type='search')['arch']
        maintenance_list = self.env['maintenance.request'].get_view(view_type='list')['arch']
        maintenance_search = self.env['maintenance.request'].get_view(view_type='search')['arch']
        dashboard_form = self.env['car.rental.dashboard'].with_user(
            self.user_manager).get_view(view_type='form')['arch']
        settings_form = self.env['res.config.settings'].get_view(view_type='form')['arch']
        self.assertIn('create_date', contact_list)
        self.assertIn('default_order="create_date desc, id desc"', contact_list)
        self.assertIn('create_date', fleet_list)
        self.assertIn('rental_status', fleet_list)
        self.assertIn('default_order="create_date desc, id desc"', fleet_list)
        self.assertIn('rental_group_category', fleet_search)
        self.assertIn('rental_group_status', fleet_search)
        self.assertRegex(fleet_form, r'<field name="state_id"[^>]*invisible="(?:1|True)"')
        self.assertIn('default_order="request_date desc, id desc"', maintenance_list)
        self.assertIn('rental_vehicle_id', maintenance_list)
        self.assertIn('rental_group_vehicle', maintenance_search)
        self.assertIn('rental_group_request_month', maintenance_search)
        self.assertIn('default_order="create_date desc, id desc"', dashboard_form)
        self.assertIn('Created On', dashboard_form)
        self.assertIn("Require the vehicle's road licence at pickup", settings_form)
        self.assertIn("not the customer's driving licence", settings_form)
        contact_arch = ElementTree.fromstring(contact_form)
        self.assertNotIn(
            'Full date', [node.get('string') for node in contact_arch.iter('field')])
        for date_field in (
                'rental_date_of_birth',
                'rental_license_issue_date',
                'rental_license_expiry'):
            date_nodes = contact_arch.findall(".//field[@name='%s']" % date_field)
            self.assertEqual(len(date_nodes), 1)
            self.assertEqual(date_nodes[0].get('widget'), 'rental_full_date')
        for field_name in (
                'rental_omang_document_ids',
                'rental_passport_document_ids',
                'rental_license_document_ids'):
            field_markup = contact_form.split('name="%s"' % field_name, 1)[1].split('/>', 1)[0]
            self.assertNotIn('required=', field_markup)
        self.assertEqual(self.env['res.partner']._fields['rental_cin'].size, 9)
        self.assertEqual(self.env['res.partner']._fields['rental_passport_number'].size, 20)
        self.assertEqual(self.env['res.partner']._fields['rental_driving_license'].size, 20)

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
            form.rental_identity_type = 'omang'
            form.rental_cin = '123456789'
            form.rental_date_of_birth = fields.Date.today() - timedelta(days=365 * 30)
            self.assertGreaterEqual(form.rental_age, 21)
            self.assertFalse(form.rental_is_underage)
            form.rental_driving_license = '12345678901234'
            form.rental_license_issue_date = fields.Date.today() - timedelta(days=365 * 3)
            form.rental_license_expiry = fields.Date.today() + timedelta(days=365 * 2)
            form.rental_omang_document_ids.add(self._attachment('form-omang.png'))
            form.rental_license_document_ids.add(self._attachment('form-licence.png'))
        self.assertTrue(form.record.rental_enabled)
        self.assertEqual(form.record.rental_cin, '123456789')
        self.assertNotIn('rental_birth_date_full', self.env['res.partner']._fields)

        with Form(form.record) as passport_form:
            passport_form.rental_identity_type = 'passport'
            self.assertFalse(passport_form.rental_cin)
            passport_form.rental_passport_number = 'P12345678'
            passport_form.rental_passport_document_ids.add(self._attachment('form-passport.png'))
        self.assertEqual(form.record.rental_identity_number, 'P12345678')
        self.assertFalse(form.record.rental_cin)

    def test_customer_save_prompts_for_documents(self):
        self.env.user.write({
            'group_ids': [fields.Command.link(
                self.env.ref('car_rental_management_odoo.group_car_rental_agent').id)],
        })
        today = fields.Date.today()
        customer = Form(self.env['res.partner'])
        customer.name = 'Customer Missing Documents'
        customer.street = '10 Main Street'
        customer.rental_enabled = True
        customer.rental_postal_address = 'PO Box 10'
        customer.rental_identity_type = 'omang'
        customer.rental_cin = '123456789'
        customer.rental_date_of_birth = today - timedelta(days=365 * 30)
        customer.rental_driving_license = '12345678901234'
        customer.rental_license_issue_date = today - timedelta(days=365 * 3)
        customer.rental_license_expiry = today + timedelta(days=365 * 2)
        with self.assertRaisesRegex(ValidationError, 'Upload the selected Omang or passport document'):
            customer.save()

        underage = Form(self.env['res.partner'])
        underage.name = 'Underage Form Customer'
        underage.street = '10 Main Street'
        underage.rental_enabled = True
        underage.rental_postal_address = 'PO Box 10'
        underage.rental_identity_type = 'omang'
        underage.rental_cin = '987654321'
        underage.rental_date_of_birth = fields.Date.today() - timedelta(days=365 * 20)
        self.assertTrue(underage.rental_is_underage)
        underage.rental_driving_license = '98765432101234'
        underage.rental_license_issue_date = fields.Date.today() - timedelta(days=365 * 3)
        underage.rental_license_expiry = fields.Date.today() + timedelta(days=365 * 2)
        underage.rental_omang_document_ids.add(self._attachment('underage-omang.png'))
        underage.rental_license_document_ids.add(self._attachment('underage-licence.png'))
        with self.assertRaisesRegex(ValidationError, '21'):
            underage.save()

    def test_staff_can_read_fleet_without_managing_it(self):
        vehicle = self._make_vehicle()
        staff_vehicle = vehicle.with_user(self.user_agent)
        data = staff_vehicle.read(['license_plate', 'model_id', 'rental_status'])[0]
        self.assertEqual(data['license_plate'], vehicle.license_plate)
        with self.assertRaises(AccessError), self.cr.savepoint():
            staff_vehicle.write({'license_plate': 'NOT-ALLOWED'})
        partner = self._make_partner()
        with Form(partner.with_user(self.user_agent)) as form:
            form.rental_cin = '111222333'
        self.assertEqual(partner.rental_cin, '111222333')

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
