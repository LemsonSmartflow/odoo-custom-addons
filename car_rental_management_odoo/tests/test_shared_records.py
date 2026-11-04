"""Shared standard records behind the rental: one Contact, one Fleet vehicle.

Rewritten for the 19.0.8.0.0 architecture where car.rental.customer and
car.rental.vehicle are gone: the rental profile lives directly on res.partner
and the rental unit directly on fleet.vehicle, with company-scoped references
and shared counts computed from those standard records.
"""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import RentalTestCommon


@tagged('post_install', '-at_install')
class TestSharedRecords(RentalTestCommon):

    def test_contact_is_the_profile_and_the_invoice_partner(self):
        partner = self._make_partner()
        self.assertTrue(partner.rental_enabled)
        self.assertEqual(partner.action_rental_profile()['res_model'], 'res.partner')
        self.assertEqual(partner.action_rental_profile()['res_id'], partner.id)
        rental = self._make_rental(self._make_reservation(partner=partner))
        self.assertEqual(rental.partner_id, partner)
        rental.action_invoice()
        invoice = rental.invoice_ids
        self.assertEqual(invoice.partner_id, partner)
        partner.write({
            'name': 'Updated Contact', 'email': 'updated@example.test',
            'phone': '12345', 'street': 'New physical address'})
        self.assertEqual(invoice.partner_id.email, 'updated@example.test')
        self.assertEqual(invoice.partner_id.street, 'New physical address')
        self.assertEqual(invoice.company_id, self.company)
        self.assertEqual(partner.rental_reservations_count, 1)
        self.assertEqual(partner.rental_rentals_count, 1)

    def test_existing_contact_is_reused_as_the_rental_customer(self):
        dashboard = self.env.ref('car_rental_management_odoo.car_rental_dashboard_record')
        before = dashboard.total_customers
        existing = self.env['res.partner'].create({
            'name': 'Existing Person', 'company_type': 'person',
            'street': 'Physical address', 'rental_postal_address': 'Postal address',
            'email': 'person@example.test', 'rental_enabled': True,
            'rental_identity_type': 'omang',
            'rental_cin': '123456789',
            'rental_date_of_birth': fields.Date.today() - timedelta(days=365 * 30),
            'rental_driving_license': '12345678901234',
            'rental_license_issue_date': fields.Date.today() - timedelta(days=365 * 3),
            'rental_license_expiry': fields.Date.today() + timedelta(days=365 * 2),
            'rental_omang_document_ids': [(6, 0, [self._attachment('omang-existing.png').id])],
            'rental_license_document_ids': [(6, 0, [self._attachment('licence-existing.png').id])],
        })
        # Confirmation runs the eligibility checks against the contact's own stored details.
        reservation = self._make_reservation(partner=existing)
        rental = self._make_rental(reservation)
        self.assertEqual(reservation.partner_id, existing)
        self.assertEqual(rental.partner_id, existing)
        self.assertEqual(existing.action_rental_profile()['res_id'], existing.id)
        self.assertEqual(existing.rental_reservations_count, 1)
        self.assertEqual(existing.rental_rentals_count, 1)
        dashboard.invalidate_recordset()
        self.assertEqual(dashboard.total_customers, before + 1)

    def test_one_fleet_vehicle_backs_the_rental_unit(self):
        vehicle = self._make_vehicle(odometer=1500.0)
        fleet = vehicle
        self.assertEqual(vehicle.action_rental_profile()['res_model'], 'fleet.vehicle')
        self.assertEqual(vehicle.action_rental_profile()['res_id'], fleet.id)
        fleet.write({'license_plate': 'SHARED-123', 'color': 'Blue'})
        self.assertEqual(vehicle.license_plate, 'SHARED-123')
        self.assertEqual(fleet.color, 'Blue')
        self.env['fleet.vehicle.odometer'].create({
            'vehicle_id': fleet.id, 'value': 1700.0, 'date': fields.Date.today()})
        vehicle.invalidate_recordset(['odometer'])
        self.assertEqual(vehicle.odometer, 1700.0)
        # Fuel type is a plain fleet value now: the legacy petrol/gasoline translation is gone.
        fleet.write({'fuel_type': 'diesel'})
        self.assertEqual(vehicle.fuel_type, 'diesel')
        reservation = self._make_reservation(vehicle=vehicle)
        self.assertEqual(reservation.vehicle_id, fleet)
        self.assertEqual(reservation.category_id, vehicle.rental_category_id)
        self.assertEqual(vehicle.rental_status, 'reserved')
        rental = self._make_rental(reservation)
        self._complete_pickup_inspection(rental)
        self.assertEqual(rental.initial_mileage, 1700.0)
        self.assertEqual(vehicle.rental_reservations_count, 1)
        self.assertEqual(vehicle.rental_rentals_count, 1)

    def test_existing_fleet_vehicle_is_reused_as_the_rental_unit(self):
        base = self._make_vehicle()
        before = self.env['fleet.vehicle'].search_count([('company_id', '=', self.company.id)])
        fleet = self.env['fleet.vehicle'].create({
            'model_id': base.model_id.id, 'license_plate': 'EXISTING-1',
            'company_id': self.company.id})
        self.assertEqual(fleet.rental_category_id, fleet.category_id)
        fleet.action_activate()
        self.assertEqual(fleet.rental_status, 'available')
        reservation = self._make_reservation(vehicle=fleet)
        rental = self._make_rental(reservation)
        self.assertEqual(reservation.vehicle_id, fleet)
        self.assertEqual(rental.vehicle_id, fleet)
        self.assertEqual(fleet.action_rental_profile()['res_id'], fleet.id)
        self.assertEqual(
            self.env['fleet.vehicle'].search_count([('company_id', '=', self.company.id)]),
            before + 1)

    def test_references_and_records_are_company_scoped(self):
        reservation = self._make_reservation()
        rental = self._make_rental(reservation)
        self.assertRegex(reservation.reference, r'^RES [A-Z]{3} \d{3,}$')
        self.assertRegex(rental.reference, r'^REN [A-Z]{3} \d{3,}$')
        month = reservation.start_date.strftime('%Y.%m')
        for model, prefix in (('car.rental.reservation', 'RES'), ('car.rental.rental', 'REN')):
            sequence = self.env['ir.sequence'].sudo().search([
                ('code', '=', '%s.%s.%s' % (model, self.company.id, month))], limit=1)
            self.assertTrue(sequence, model)
            self.assertEqual(sequence.company_id, self.company)
            self.assertTrue(sequence.prefix.startswith(prefix))
        self.assertEqual(rental.company_id, self.company)
        rental.action_invoice()
        self.assertEqual(rental.invoice_ids.company_id, self.company)
        # The same reference text is valid in another company: uniqueness is company-scoped.
        other = self.env['res.company'].create({'name': 'Twin Rental Company'})
        ctx = dict(self.env.context, allowed_company_ids=[self.company.id, other.id])
        category = reservation.vehicle_id.category_id
        other_zone = self.env['car.rental.zone'].with_context(ctx).create({
            'name': 'Twin Destination', 'company_id': other.id})
        other_vehicle = self.env['fleet.vehicle'].with_context(ctx).create({
            'model_id': reservation.vehicle_id.model_id.id, 'license_plate': 'TWIN-1',
            'company_id': other.id,
            'rental_status': 'available'})
        start = (fields.Datetime.now() + timedelta(days=1)).replace(
            hour=8, minute=0, second=0, microsecond=0)
        twin = self.env['car.rental.reservation'].with_context(ctx).create({
            'company_id': other.id, 'partner_id': self._make_partner().id,
            'vehicle_id': other_vehicle.id, 'destination_id': other_zone.id,
            'category_id': category.id, 'reference': reservation.reference,
            'pickup_datetime': start, 'expected_return_datetime': start + timedelta(days=3)})
        self.assertEqual(twin.reference, reservation.reference)
        # While a second booking in the rental company must pick a new reference.
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['car.rental.reservation'].create({
                'company_id': self.company.id, 'partner_id': self._make_partner().id,
                'destination_id': reservation.destination_id.id,
                'category_id': reservation.category_id.id,
                'vehicle_id': reservation.vehicle_id.id,
                'reference': reservation.reference,
                'pickup_datetime': reservation.pickup_datetime + timedelta(days=30),
                'expected_return_datetime': reservation.expected_return_datetime + timedelta(days=30)})
