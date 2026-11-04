"""Business rules adapted to the standard-model architecture.

Mirrors the former custom-model suite: references, 24-hour periods and
same-day returns, adjacent allocations, eligibility at confirmation, the
deposit policy, identity/signature defaults, dirty-return settlement and the
dashboard scope. Only genuinely removed behaviour has been dropped.
"""
from datetime import datetime, timedelta

from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import Form, tagged

from .common import RentalTestCommon, PNG_SIGNATURE


@tagged('post_install', '-at_install')
class TestBusinessRules(RentalTestCommon):

    def test_references_are_editable_unique_and_never_saved_as_new(self):
        reservation = self._make_reservation(confirm=True)
        reservation.reference = 'CUSTOM RESERVATION'
        rental = self._make_rental(reservation)
        rental.reference = 'CUSTOM RENTAL'
        self.assertEqual(rental.reference, 'CUSTOM RENTAL')
        # A confirmed, linked booking reference can still be corrected.
        reservation.reference = 'UPDATED RESERVATION'
        with self.assertRaises(ValidationError), self.cr.savepoint():
            rental.reference = ''
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['car.rental.reservation'].create({
                'company_id': self.company.id,
                'partner_id': self._make_partner().id,
                'destination_id': reservation.destination_id.id,
                'category_id': reservation.category_id.id,
                'vehicle_id': reservation.vehicle_id.id,
                'reference': 'UPDATED RESERVATION',
                'pickup_datetime': reservation.pickup_datetime + timedelta(days=30),
                'expected_return_datetime': reservation.expected_return_datetime + timedelta(days=30),
            })
        auto = self.env['car.rental.reservation'].create({
            'company_id': self.company.id,
            'partner_id': self._make_partner().id,
            'destination_id': reservation.destination_id.id,
            'category_id': reservation.category_id.id,
            'vehicle_id': reservation.vehicle_id.id,
            'pickup_datetime': reservation.pickup_datetime + timedelta(days=31),
            'expected_return_datetime': reservation.expected_return_datetime + timedelta(days=31),
        })
        self.assertRegex(auto.reference, r'^RES [A-Z]{3} \d{3,}$')

    def test_twenty_four_hour_periods_and_same_day_return(self):
        start = datetime.combine(fields.Date.today() + timedelta(days=10), datetime.min.time()).replace(hour=14)
        partner = self._make_partner()
        vehicle = self._make_vehicle()
        zone = self._make_zone()
        category = vehicle.rental_category_id
        self._make_rate_rule(category, zone, daily_rate=100.0)
        reservation = self.env['car.rental.reservation'].create({
            'company_id': self.company.id,
            'partner_id': partner.id,
            'category_id': category.id,
            'destination_id': zone.id,
            'vehicle_id': vehicle.id,
            'pickup_datetime': start,
            'expected_return_datetime': start + timedelta(hours=24),
        })
        self.assertEqual(reservation.number_of_days, 1)
        self.assertEqual(reservation.amount_untaxed, 100)
        reservation.write({'expected_return_datetime': start + timedelta(hours=24, seconds=1)})
        self.assertEqual(reservation.number_of_days, 2)
        self.assertEqual(reservation.amount_untaxed, 200)
        reservation.write({'expected_return_datetime': start + timedelta(hours=2)})
        self.assertEqual(reservation.number_of_days, 1)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            reservation.write({'expected_return_datetime': start})

    def test_entering_rental_days_calculates_return_time(self):
        start = datetime.combine(fields.Date.today() + timedelta(days=10), datetime.min.time()).replace(
            hour=14, minute=30)
        partner = self._make_partner()
        vehicle = self._make_vehicle()
        zone = self._make_zone()
        self._make_rate_rule(vehicle.rental_category_id, zone)
        reservation = self.env['car.rental.reservation'].create({
            'company_id': self.company.id,
            'partner_id': partner.id,
            'category_id': vehicle.rental_category_id.id,
            'destination_id': zone.id,
            'vehicle_id': vehicle.id,
            'pickup_datetime': start,
            'number_of_days': 3,
        })
        self.assertEqual(reservation.expected_return_datetime, start + timedelta(days=3))
        self.assertEqual(reservation.number_of_days, 3)
        self.assertEqual(reservation.amount_untaxed, 300)

        reservation.write({'number_of_days': 2})
        self.assertEqual(reservation.expected_return_datetime, start + timedelta(days=2))

        journey = self.env['car.rental.journey'].create({
            'pickup_datetime': start,
            'number_of_days': 4,
        })
        self.assertEqual(journey.expected_return_datetime, start + timedelta(days=4))
        journey.write({'number_of_days': 1})
        self.assertEqual(journey.expected_return_datetime, start + timedelta(days=1))

        journey = self.env['car.rental.journey'].create({'details_started': True})
        with Form(journey) as form:
            form.pickup_datetime = start
            form.number_of_days = 4
            self.assertEqual(form.expected_return_datetime, start + timedelta(days=4))

    def test_adjacent_hour_allocations_same_day(self):
        start = datetime.combine(fields.Date.today() + timedelta(days=10), datetime.min.time()).replace(hour=10)
        partner = self._make_partner()
        vehicle = self._make_vehicle()
        zone = self._make_zone()
        category = vehicle.rental_category_id
        self._make_rate_rule(category, zone)
        vals = {
            'company_id': self.company.id,
            'partner_id': partner.id,
            'vehicle_id': vehicle.id,
            'destination_id': zone.id,
            'category_id': category.id,
            'pickup_datetime': start,
            'expected_return_datetime': start + timedelta(hours=2),
        }
        self.env['car.rental.reservation'].create(dict(vals))
        self.env['car.rental.reservation'].create(dict(
            vals,
            pickup_datetime=start + timedelta(hours=2),
            expected_return_datetime=start + timedelta(hours=4),
        ))
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['car.rental.reservation'].create(dict(
                vals,
                pickup_datetime=start + timedelta(hours=1),
                expected_return_datetime=start + timedelta(hours=3),
            ))

    def test_age_and_documents_at_confirmation(self):
        reservation = self._make_reservation(confirm=False)
        pickup = reservation.pickup_datetime.date()
        partner = reservation.partner_id
        with self.assertRaisesRegex(ValidationError, '21'), self.cr.savepoint():
            partner.write({'rental_date_of_birth': pickup.replace(year=pickup.year - 20)})
        partner.rental_date_of_birth = fields.Date.today().replace(year=fields.Date.today().year - 21)
        reservation.action_confirm()
        self.assertEqual(reservation.status, 'confirmed')

    def test_rental_customer_requires_current_age_and_unexpired_license(self):
        today = fields.Date.today()
        profile = {
            'name': self._unique('Prospective renter'),
            'company_type': 'person',
            'street': '1 Test Street',
            'rental_postal_address': 'PO Box 1',
            'rental_cin': '123456789',
            'rental_date_of_birth': today.replace(year=today.year - 20),
            'rental_driving_license': '12345678901234',
            'rental_license_issue_date': today.replace(year=today.year - 3),
            'rental_license_expiry': today.replace(year=today.year + 2),
            'rental_enabled': True,
            'rental_omang_document_ids': [(6, 0, [self._attachment('eligibility-omang.png').id])],
            'rental_license_document_ids': [(6, 0, [self._attachment('eligibility-licence.png').id])],
        }
        with self.assertRaisesRegex(ValidationError, '21'), self.cr.savepoint():
            self.env['res.partner'].create(profile)

        profile.update({
            'name': self._unique('Expired-license renter'),
            'rental_date_of_birth': today.replace(year=today.year - 30),
            'rental_license_expiry': today - timedelta(days=1),
        })
        with self.assertRaisesRegex(ValidationError, 'expired'), self.cr.savepoint():
            self.env['res.partner'].create(profile)

        contact = self.env['res.partner'].create({
            key: value for key, value in profile.items() if key != 'rental_enabled'
        })
        with self.assertRaisesRegex(ValidationError, 'expired'), self.cr.savepoint():
            contact.write({'rental_enabled': True})

    def test_rental_customer_requires_selected_identity_and_licence_documents(self):
        today = fields.Date.today()
        with self.assertRaisesRegex(ValidationError, 'Upload the selected'), self.cr.savepoint():
            self.env['res.partner'].create({
                'name': self._unique('Missing documents'),
                'company_type': 'person',
                'street': '1 Test Street',
                'rental_postal_address': 'PO Box 1',
                'rental_identity_type': 'omang',
                'rental_cin': '123456789',
                'rental_date_of_birth': today.replace(year=today.year - 30),
                'rental_driving_license': '12345678901234',
                'rental_license_issue_date': today.replace(year=today.year - 3),
                'rental_license_expiry': today.replace(year=today.year + 2),
                'rental_enabled': True,
            })

    def test_identity_number_formats_and_selected_identity(self):
        today = fields.Date.today()
        partner = self.env['res.partner'].create({
            'name': self._unique('Passport renter'),
            'company_type': 'person',
            'street': '1 Test Street',
            'rental_postal_address': 'PO Box 1',
            'rental_identity_type': 'passport',
            'rental_passport_number': 'P12345678',
            'rental_date_of_birth': today.replace(year=today.year - 30),
            'rental_driving_license': '12345678901234',
            'rental_license_issue_date': today.replace(year=today.year - 3),
            'rental_license_expiry': today.replace(year=today.year + 2),
            'rental_passport_document_ids': [(6, 0, [self._attachment('passport.png').id])],
            'rental_license_document_ids': [(6, 0, [self._attachment('licence.png').id])],
            'rental_enabled': True,
        })
        self.assertEqual(partner.rental_identity_number, 'P12345678')
        with self.assertRaisesRegex(ValidationError, 'exactly 9 digits'), self.cr.savepoint():
            self.env['res.partner'].create({
                'name': self._unique('Invalid Omang'),
                'rental_cin': '12345678A',
            })
        with self.assertRaisesRegex(ValidationError, 'exactly 9 digits'), self.cr.savepoint():
            self.env['res.partner'].create({
                'name': self._unique('Oversized Omang'),
                'rental_cin': '1234567890',
            })
        with self.assertRaisesRegex(ValidationError, '6 to 20 letters or digits'), self.cr.savepoint():
            partner.write({'rental_driving_license': 'LIC-123456'})

    def test_deposit_cannot_be_overridden_anywhere(self):
        reservation = self._make_reservation(confirm=False)
        with self.assertRaisesRegex(ValidationError, 'approved pricing'), self.cr.savepoint():
            reservation.write({'deposit_required': 1})
        rental = self._make_rental(self._make_reservation())
        with self.assertRaises(ValidationError), self.cr.savepoint():
            rental.write({'deposit_required': 1})
        event = self.env['car.rental.deposit.transaction'].create({
            'rental_id': rental.id,
            'kind': 'collect',
            'amount': 40,  # 40% of the agreed daily rate, below the 50% floor
        })
        with self.assertRaises(AccessError), self.cr.savepoint():
            event.with_user(self.user_agent).action_post()
        with self.assertRaisesRegex(ValidationError, '50%'), self.cr.savepoint():
            event.action_post()

    def test_identity_and_signature_name_defaults(self):
        vehicle = self._make_vehicle()
        vehicle.write({'license_plate': 'AUTO-PLATE'})
        self.assertEqual(vehicle.license_plate, 'AUTO-PLATE')
        rental = self._make_rental(self._make_reservation(confirm=True))
        self.assertEqual(rental.agreement_signed_by, rental.partner_id.display_name)
        check = self.env['car.rental.check'].create({
            'rental_id': rental.id,
            'kind': 'pickup',
            'mileage': rental.vehicle_id.odometer,
            'fuel_level': 'full',
            'exterior': 'Good',
            'interior': 'Good',
            'tyres': 'Good',
            'accessories': 'Good',
        })
        self.assertEqual(check.acknowledged_by, rental.partner_id.display_name)

    def test_dirty_return_invoice_and_deposit_settlement(self):
        reservation = self._make_reservation(confirm=False, days=2)
        rule = reservation.pricing_rule_id
        rule.action_draft()
        rule.cleaning_fee = 30
        rule.action_approve()
        reservation.action_reprice()
        reservation.action_confirm()
        rental = self._make_rental(reservation)
        self._complete_pickup_inspection(rental)
        self._sign_agreement(rental)
        self._collect_deposit(rental)
        rental.vehicle_id._refresh_reserved_status()
        rental.action_start_rental()
        check = self._complete_return_inspection(rental, clean='no', fuel_level='bar_3')
        rental.action_return_vehicle()
        invoice = rental.invoice_ids.filtered(lambda m: m.rental_invoice_kind == 'cleaning')
        self.assertEqual(len(invoice), 1)
        self.assertEqual(invoice.amount_total, 30)
        self.assertEqual(invoice.state, 'draft')
        with self.assertRaisesRegex(ValidationError, 'Settle'), self.cr.savepoint():
            self.env['car.rental.deposit.transaction'].create({
                'rental_id': rental.id,
                'kind': 'refund',
                'amount': rental.deposit_held,
            }).action_post()
        invoice.action_post()
        event = self.env['car.rental.deposit.transaction'].create({
            'rental_id': rental.id,
            'kind': 'retain',
            'amount': 30,
            'charge_invoice_id': invoice.id,
        })
        event.action_post()
        self.assertEqual(invoice.amount_residual, 0)
        self.assertEqual(rental.deposit_held, rental.deposit_required - 30)
        refund = self.env['car.rental.deposit.transaction'].create({
            'rental_id': rental.id,
            'kind': 'refund',
            'amount': rental.deposit_held,
        })
        refund.action_post()
        self.assertEqual(rental.deposit_held, 0)
        self.assertEqual(check.fuel_level, 'bar_3')

    def test_monthly_references_and_dashboard_scope(self):
        reservation = self._make_reservation(confirm=True)
        rental = self._make_rental(reservation)
        self.assertRegex(reservation.reference, r'^RES [A-Z]{3} \d{3,}$')
        self.assertRegex(rental.reference, r'^REN [A-Z]{3} \d{3,}$')
        dashboard = self.env.ref('car_rental_management_odoo.car_rental_dashboard_record')
        before = dashboard.total_vehicles
        # A setup vehicle is not operational and must not inflate the total.
        self._make_vehicle(status='setup')
        dashboard.invalidate_recordset()
        self.assertEqual(dashboard.total_vehicles, before)
        self.assertEqual(dashboard.company_id, self.env.company)
        self.assertIn(dashboard, self.env['car.rental.dashboard'].search([('company_id', 'in', self.env.company.ids)]))
        self.assertFalse(self.env['car.rental.dashboard'].search([('company_id', '=', 0)]))

    def test_existing_booking_cleaning_fee_can_be_set_before_signature(self):
        reservation = self._make_reservation(confirm=True)
        rule = reservation.pricing_rule_id
        rule.action_draft()
        rule.cleaning_fee = 40
        rule.action_approve()
        reservation.action_refresh_cleaning_fee()
        self.assertEqual(reservation.cleaning_fee, 40)
        rental = self._make_rental(reservation)
        rental.write({'agreement_signature': PNG_SIGNATURE})
        rental.action_sign_agreement()
        with self.assertRaisesRegex(ValidationError, 'before signing'), self.cr.savepoint():
            reservation.action_refresh_cleaning_fee()
