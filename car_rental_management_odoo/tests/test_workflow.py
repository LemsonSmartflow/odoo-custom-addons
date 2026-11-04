"""Core reservation / rental workflow tests against the extended standard models."""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged

from .common import RentalTestCommon


@tagged('post_install', '-at_install')
class TestReservationWorkflow(RentalTestCommon):

    def test_reservation_reference_is_monthly_and_validated(self):
        reservation = self._make_reservation()
        self.assertRegex(reservation.reference, r'^RES [A-Z]{3} \d{3,}$')
        self.assertNotEqual(reservation.reference, 'New')

    def test_duplicate_reference_is_rejected(self):
        first = self._make_reservation()
        with self.assertRaises(ValidationError):
            self.env['car.rental.reservation'].create({
                'company_id': self.company.id,
                'partner_id': self._make_partner().id,
                'reference': first.reference,
                'destination_id': first.destination_id.id,
                'category_id': first.category_id.id,
                'vehicle_id': first.vehicle_id.id,
                'pickup_datetime': first.pickup_datetime + timedelta(days=30),
                'expected_return_datetime': first.expected_return_datetime + timedelta(days=30),
            })

    def test_pricing_is_derived_from_the_approved_rule(self):
        reservation = self._make_reservation(
            days=2, daily_rate=120.0, deposit_ratio=0.5, cleaning_fee=30.0)
        self.assertTrue(reservation.pricing_rule_id)
        self.assertEqual(reservation.quoted_daily_rate, 120.0)
        self.assertEqual(reservation.deposit_required, 60.0)
        self.assertEqual(reservation.cleaning_fee, 30.0)
        self.assertEqual(reservation.number_of_days, 2)
        self.assertEqual(reservation.amount_untaxed, 240.0)

    def test_confirm_requires_an_approved_pricing_rule(self):
        partner = self._make_partner()
        vehicle = self._make_vehicle()
        zone = self._make_zone()
        start = (fields.Datetime.now() + timedelta(days=1)).replace(
            hour=8, minute=0, second=0, microsecond=0)
        reservation = self.env['car.rental.reservation'].create({
            'company_id': self.company.id, 'partner_id': partner.id,
            'destination_id': zone.id, 'category_id': vehicle.rental_category_id.id,
            'vehicle_id': vehicle.id, 'pickup_datetime': start,
            'expected_return_datetime': start + timedelta(days=2)})
        with self.assertRaises(ValidationError):
            reservation.action_confirm()

    def test_confirmed_reservation_details_are_locked(self):
        reservation = self._make_reservation()
        with self.assertRaises(ValidationError):
            reservation.write({'pickup_datetime': reservation.pickup_datetime + timedelta(days=5)})

    def test_vehicle_cannot_be_double_booked(self):
        partner = self._make_partner()
        vehicle = self._make_vehicle()
        zone = self._make_zone()
        self._make_rate_rule(vehicle.rental_category_id, zone)
        start = (fields.Datetime.now() + timedelta(days=1)).replace(
            hour=8, minute=0, second=0, microsecond=0)
        base = {
            'company_id': self.company.id, 'destination_id': zone.id,
            'category_id': vehicle.rental_category_id.id, 'vehicle_id': vehicle.id}
        self.env['car.rental.reservation'].create(dict(
            base, partner_id=partner.id, pickup_datetime=start,
            expected_return_datetime=start + timedelta(days=2)))
        with self.assertRaises(ValidationError):
            self.env['car.rental.reservation'].create(dict(
                base, partner_id=partner.id, pickup_datetime=start + timedelta(days=1),
                expected_return_datetime=start + timedelta(days=3)))

    def test_cancelled_reservation_releases_the_vehicle(self):
        partner = self._make_partner()
        vehicle = self._make_vehicle()
        zone = self._make_zone()
        self._make_rate_rule(vehicle.rental_category_id, zone)
        start = (fields.Datetime.now() + timedelta(days=1)).replace(
            hour=8, minute=0, second=0, microsecond=0)
        base = {
            'company_id': self.company.id, 'destination_id': zone.id,
            'category_id': vehicle.rental_category_id.id, 'vehicle_id': vehicle.id}
        first = self.env['car.rental.reservation'].create(dict(
            base, partner_id=partner.id, pickup_datetime=start,
            expected_return_datetime=start + timedelta(days=2)))
        first.action_cancel()
        second = self.env['car.rental.reservation'].create(dict(
            base, partner_id=partner.id, pickup_datetime=start,
            expected_return_datetime=start + timedelta(days=2)))
        self.assertTrue(second.id)

    def test_rate_override_requires_a_manager(self):
        partner = self._make_partner()
        vehicle = self._make_vehicle()
        zone = self._make_zone()
        self._make_rate_rule(vehicle.rental_category_id, zone, daily_rate=100.0)
        start = (fields.Datetime.now() + timedelta(days=1)).replace(
            hour=8, minute=0, second=0, microsecond=0)
        reservation = self.env['car.rental.reservation'].create({
            'company_id': self.company.id, 'partner_id': partner.id,
            'destination_id': zone.id, 'category_id': vehicle.rental_category_id.id,
            'vehicle_id': vehicle.id, 'pickup_datetime': start,
            'expected_return_datetime': start + timedelta(days=2)})
        reservation.write({'proposed_rate': 80.0, 'override_reason': 'Loyal customer'})
        reservation.action_request_override()
        with self.assertRaises(AccessError):
            reservation.with_user(self.user_agent).action_approve_override()
        reservation.with_user(self.user_manager).action_approve_override()
        self.assertEqual(reservation.override_state, 'approved')
        self.assertEqual(reservation.quoted_daily_rate, 80.0)


@tagged('post_install', '-at_install')
class TestRentalWorkflow(RentalTestCommon):

    def test_rental_reference_and_single_rental_per_reservation(self):
        reservation = self._make_reservation()
        rental = self._make_rental(reservation)
        self.assertRegex(rental.reference, r'^REN [A-Z]{3} \d{3,}$')
        with self.assertRaises(ValidationError):
            self._make_rental(reservation)

    def test_rental_requires_a_confirmed_reservation(self):
        reservation = self._make_reservation(confirm=False)
        with self.assertRaises(ValidationError):
            self._make_rental(reservation)

    def test_rental_status_cannot_be_written_directly(self):
        rental = self._make_rental(self._make_reservation())
        with self.assertRaises(ValidationError):
            rental.write({'status': 'ongoing'})

    def test_pickup_inspection_requires_complete_fields(self):
        rental = self._make_rental(self._make_reservation())
        with self.assertRaises(ValidationError):
            self._complete_pickup_inspection(
                rental, signature=False, acknowledged_by=False, photo_ids=[(6, 0, [])])
        pickup_mileage = rental.vehicle_id.odometer + 25
        self._complete_pickup_inspection(rental, mileage=pickup_mileage, user=self.user_agent)
        self.assertTrue(rental.pickup_inspection_done)
        self.assertEqual(rental.initial_mileage, pickup_mileage)
        self.assertEqual(rental.vehicle_id.odometer, pickup_mileage)
        self.assertTrue(self.env['fleet.vehicle.odometer'].search_count([
            ('vehicle_id', '=', rental.vehicle_id.id), ('value', '=', pickup_mileage)]))

    def test_pickup_inspection_mileage_cannot_trail_odometer(self):
        rental = self._make_rental(self._make_reservation())
        with self.assertRaises(ValidationError):
            self._complete_pickup_inspection(rental, mileage=rental.vehicle_id.odometer - 100)

    def test_one_completed_inspection_per_kind(self):
        rental = self._make_rental(self._make_reservation())
        self._complete_pickup_inspection(rental)
        with self.assertRaises(ValidationError):
            self._complete_pickup_inspection(rental)

    def test_agreement_requires_terms_signature_and_name(self):
        rental = self._make_rental(self._make_reservation())
        with self.assertRaises(ValidationError):
            rental.action_sign_agreement()
        self._sign_agreement(rental)
        self.assertEqual(rental.agreement_state, 'signed')

    def test_deposit_cannot_exceed_the_required_amount(self):
        rental = self._make_rental(self._make_reservation())
        deposit = self.env['car.rental.deposit.transaction'].create({
            'rental_id': rental.id, 'kind': 'collect',
            'amount': rental.deposit_required + 50.0})
        with self.assertRaises(ValidationError):
            deposit.action_post()

    def test_full_handover_flow_starts_the_rental(self):
        rental = self._ready_to_handover()
        rental.action_start_rental()
        self.assertEqual(rental.status, 'ongoing')
        self.assertEqual(rental.vehicle_id.rental_status, 'rented')
        self.assertTrue(rental.actual_pickup_datetime)

    def test_handover_requires_the_security_deposit(self):
        rental = self._make_rental(self._make_reservation())
        self._complete_pickup_inspection(rental)
        self._sign_agreement(rental)
        rental.vehicle_id._refresh_reserved_status()
        with self.assertRaises(ValidationError):
            rental.action_start_rental()

    def test_return_flow_records_mileage_and_releases_vehicle(self):
        rental = self._ready_to_handover()
        rental.action_start_rental()
        mileage = rental.initial_mileage + 400
        self._complete_return_inspection(rental, mileage=mileage)
        rental.action_return_vehicle()
        self.assertEqual(rental.status, 'returned')
        self.assertEqual(rental.final_mileage, mileage)
        self.assertEqual(rental.distance_travelled, 400)
        self.assertEqual(rental.vehicle_id.odometer, mileage)
        self.assertIn(rental.vehicle_id.rental_status, ('inspection', 'damaged'))

    def test_vehicle_service_interval_sets_next_mileage_and_due_alert(self):
        vehicle = self._make_vehicle(odometer=12500, rental_service_interval=5000)
        self.assertEqual(vehicle.rental_next_service_mileage, 17500)
        vehicle._operational_update({'odometer': 17000})
        self.assertTrue(vehicle.rental_service_due)

    def test_return_inspection_mileage_cannot_trail_pickup(self):
        rental = self._ready_to_handover()
        rental.action_start_rental()
        with self.assertRaises(ValidationError):
            self._complete_return_inspection(rental, mileage=rental.initial_mileage - 10)

    def test_late_return_charges_the_agreed_daily_rate(self):
        partner = self._make_partner()
        vehicle = self._make_vehicle()
        zone = self._make_zone()
        self._make_rate_rule(vehicle.rental_category_id, zone, daily_rate=100.0)
        start = (fields.Datetime.now() - timedelta(days=5)).replace(
            hour=8, minute=0, second=0, microsecond=0)
        reservation = self.env['car.rental.reservation'].create({
            'company_id': self.company.id, 'partner_id': partner.id,
            'destination_id': zone.id, 'category_id': vehicle.rental_category_id.id,
            'vehicle_id': vehicle.id, 'pickup_datetime': start,
            'expected_return_datetime': start + timedelta(days=2)})
        reservation.action_confirm()
        rental = self._ready_to_handover(reservation)
        rental.action_start_rental()
        self._complete_return_inspection(rental, mileage=rental.initial_mileage + 300)
        rental.action_return_vehicle()
        self.assertGreaterEqual(rental.late_days, 2)
        self.assertEqual(rental.late_charge, rental.late_days * reservation.quoted_daily_rate)

    def test_vehicle_activation_and_direct_status_guards(self):
        vehicle = self._make_vehicle(status='setup')
        with self.assertRaises(ValidationError):
            vehicle.write({'rental_status': 'rented'})
        vehicle.action_activate()
        self.assertEqual(vehicle.rental_status, 'available')
        with self.assertRaises(ValidationError):
            vehicle.write({'rental_status': 'reserved'})

    def test_vehicle_ready_requires_registration_and_category(self):
        vehicle = self._make_vehicle(status='available')
        vehicle.write({'license_plate': False})
        with self.assertRaises(ValidationError):
            vehicle._check_ready()

    def test_vehicle_contracts_are_optional_by_default(self):
        self.assertFalse(self.env['res.company'].default_get(
            ['rental_block_expired_documents'])['rental_block_expired_documents'])
        vehicle = self._make_vehicle()
        self.assertFalse(vehicle._rental_open_contract('Road Licence'))
        vehicle._check_ready()

    def test_insurance_is_optional_when_road_licence_is_valid(self):
        self.company.rental_block_expired_documents = True
        vehicle = self._make_vehicle()
        road_licence_type = self.env['fleet.service.type'].search([
            ('category', '=', 'contract'), ('name', '=', 'Road Licence')], limit=1)
        self.assertTrue(road_licence_type, 'The rental module must provide a Road Licence contract type.')
        with self.assertRaisesRegex(ValidationError, 'vehicle needs a current Road Licence contract'):
            vehicle._check_ready()
        self.env['fleet.vehicle.log.contract'].with_user(self.user_fleet).create({
            'vehicle_id': vehicle.id,
            'cost_subtype_id': road_licence_type.id,
            'expiration_date': fields.Date.today() + timedelta(days=30),
        })
        self.assertFalse(vehicle._rental_open_contract('Insurance'))
        vehicle._check_ready()

    def test_window_actions_return_act_window(self):
        vehicle = self._make_vehicle()
        self.assertEqual(vehicle.action_reservations()['res_model'], 'car.rental.reservation')
        self.assertEqual(vehicle.action_rentals()['res_model'], 'car.rental.rental')
        self.assertEqual(vehicle.action_book()['res_model'], 'car.rental.reservation')


@tagged('post_install', '-at_install')
class TestRentalRoles(RentalTestCommon):

    def test_manager_only_damage_approval(self):
        rental = self._ready_to_handover(self._make_reservation())
        rental.action_start_rental()
        self._complete_return_inspection(rental, new_damage=True, damage_notes='Scratched door')
        rental.action_return_vehicle()
        damage = rental.damage_ids[:1]
        self.assertTrue(damage)
        with self.assertRaises(AccessError):
            damage.with_user(self.user_agent).action_approve()
        damage.with_user(self.user_manager).action_approve()
        self.assertEqual(damage.state, 'approved')
        self.assertEqual(damage.vehicle_id.rental_status, 'damaged')

    def test_accountant_only_deposit_posting(self):
        rental = self._make_rental(self._make_reservation())
        deposit = self.env['car.rental.deposit.transaction'].create({
            'rental_id': rental.id, 'kind': 'collect', 'amount': rental.deposit_required})
        with self.assertRaises(AccessError):
            deposit.with_user(self.user_agent).action_post()
        deposit.with_user(self.user_accountant).action_post()
        self.assertEqual(deposit.state, 'posted')
        self.assertEqual(rental.deposit_held, rental.deposit_required)

    def test_fleet_manager_only_vehicle_maintenance_moves(self):
        vehicle = self._make_vehicle(status='available')
        with self.assertRaises(AccessError):
            vehicle.with_user(self.user_agent).action_mark_cleaning()
