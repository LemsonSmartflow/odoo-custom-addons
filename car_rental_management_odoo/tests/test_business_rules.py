from datetime import datetime, timedelta

from odoo import fields
from odoo.exceptions import ValidationError

from .test_workflow import TestConnectedWorkflow


class TestBusinessRules(TestConnectedWorkflow):
    def test_references_are_editable_unique_and_never_saved_as_new(self):
        self.reservation.reference = 'CUSTOM RESERVATION'
        rental = self.rental()
        rental.reference = 'CUSTOM RENTAL'
        self.assertEqual(rental.reference, 'CUSTOM RENTAL')
        # A confirmed, linked booking reference can still be corrected.
        self.reservation.reference = 'UPDATED RESERVATION'
        with self.assertRaises(ValidationError), self.cr.savepoint():
            rental.reference = ''
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['car.rental.reservation'].create({
                'reference': 'UPDATED RESERVATION', 'customer_id': self.customer.id,
                'destination_id': self.destination.id, 'category_id': self.category.id,
                'pickup_datetime': self.reservation.pickup_datetime,
                'expected_return_datetime': self.reservation.expected_return_datetime,
            })
        auto = self.env['car.rental.reservation'].create({
            'reference': False, 'customer_id': self.customer.id,
            'destination_id': self.destination.id, 'category_id': self.category.id,
            'pickup_datetime': self.reservation.pickup_datetime,
            'expected_return_datetime': self.reservation.expected_return_datetime,
        })
        self.assertRegex(auto.reference, r'^RES [A-Z]{3} \d{3,}$')

    def test_twenty_four_hour_periods_and_same_day_return(self):
        start = datetime.combine(fields.Date.today() + timedelta(days=10), datetime.min.time()).replace(hour=14)
        reservation = self.env['car.rental.reservation'].create({
            'customer_id': self.customer.id, 'category_id': self.category.id,
            'destination_id': self.destination.id, 'pickup_datetime': start,
            'expected_return_datetime': start + timedelta(hours=24),
        })
        self.assertEqual(reservation.number_of_days, 1)
        self.assertEqual(reservation.amount, 100)
        reservation.write({'expected_return_datetime': start + timedelta(hours=24, seconds=1)})
        self.assertEqual(reservation.number_of_days, 2)
        self.assertEqual(reservation.amount, 200)
        reservation.write({'expected_return_datetime': start + timedelta(hours=2)})
        self.assertEqual(reservation.number_of_days, 1)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            reservation.write({'expected_return_datetime': start})

    def test_adjacent_hour_allocations_same_day(self):
        start = datetime.combine(fields.Date.today() + timedelta(days=10), datetime.min.time()).replace(hour=10)
        vals = {'customer_id': self.customer.id, 'vehicle_id': self.vehicle.id,
                'destination_id': self.destination.id, 'pickup_datetime': start,
                'expected_return_datetime': start + timedelta(hours=2)}
        self.env['car.rental.reservation'].create(dict(vals))
        self.env['car.rental.reservation'].create(dict(vals, pickup_datetime=start + timedelta(hours=2), expected_return_datetime=start + timedelta(hours=4)))
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['car.rental.reservation'].create(dict(vals, pickup_datetime=start + timedelta(hours=1)))

    def test_age_and_documents_at_confirmation(self):
        pickup = self.reservation.pickup_datetime.date()
        self.customer.date_of_birth = pickup.replace(year=pickup.year - 20)
        with self.assertRaisesRegex(ValidationError, '21'), self.cr.savepoint():
            self.reservation.action_confirm()
        self.customer.date_of_birth = pickup.replace(year=pickup.year - 21)
        self.customer.omang_document_ids = False
        with self.assertRaisesRegex(ValidationError, 'Omang or passport'), self.cr.savepoint():
            self.reservation.action_confirm()
        self.customer.passport_document_ids = self.customer.license_document_ids
        self.reservation.action_confirm()
        self.assertEqual(self.reservation.status, 'confirmed')

    def test_deposit_cannot_be_overridden_anywhere(self):
        with self.assertRaisesRegex(ValidationError, 'approved pricing'), self.cr.savepoint():
            self.reservation.write({'deposit_required': 1})
        rental = self.rental()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            rental.write({'deposit_required': 1})
        event = self.env['car.rental.deposit.transaction'].create({'rental_id': rental.id, 'kind': 'collect', 'amount': 49})
        with self.assertRaisesRegex(ValidationError, '50%'), self.cr.savepoint():
            event.action_post()

    def test_identity_and_signature_name_defaults(self):
        self.vehicle.fleet_id = 'AUTO-PLATE'
        self.assertEqual(self.vehicle.registration_number, 'AUTO-PLATE')
        rental = self.rental()
        self.assertEqual(rental.agreement_signed_by, self.customer.display_name)
        check = self.env['car.rental.check'].create({
            'rental_id': rental.id, 'mileage': 1000, 'fuel_level': 'full',
            'exterior': 'Good', 'interior': 'Good', 'tyres': 'Good', 'accessories': 'Good',
        })
        self.assertEqual(check.acknowledged_by, self.customer.display_name)

    def test_dirty_return_invoice_and_deposit_settlement(self):
        self.rule.action_draft()
        self.rule.cleaning_fee = 30
        self.rule.action_approve()
        self.reservation.action_reprice()
        rental = self.rental()
        self.handover(rental)
        check = self.inspection(rental, 'return', 1200, clean='no', fuel_level='bar_3')
        rental.action_return_vehicle()
        invoice = rental.invoice_ids.filtered(lambda m: m.rental_invoice_kind == 'cleaning')
        self.assertEqual(len(invoice), 1)
        self.assertEqual(invoice.amount_total, 30)
        self.assertEqual(invoice.state, 'draft')
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.deposit(rental, 'refund', 100)
        invoice.action_post()
        event = self.env['car.rental.deposit.transaction'].create({
            'rental_id': rental.id, 'kind': 'retain', 'amount': 30, 'charge_invoice_id': invoice.id})
        event.action_post()
        self.assertEqual(invoice.amount_residual, 0)
        self.assertEqual(rental.deposit_held, 70)
        self.deposit(rental, 'refund', 70)
        self.assertEqual(rental.deposit_held, 0)
        self.assertEqual(check.fuel_level, 'bar_3')

    def test_monthly_references_and_dashboard_scope(self):
        rental = self.rental()
        self.assertRegex(self.reservation.reference, r'^RES [A-Z]{3} \d{3,}$')
        self.assertRegex(rental.reference, r'^REN [A-Z]{3} \d{3,}$')
        dashboard = self.env.ref('car_rental_management_odoo.car_rental_dashboard_record')
        before = dashboard.total_vehicles
        self.env['car.rental.vehicle'].create({'brand': 'Test', 'model': 'Placeholder', 'status': 'setup'})
        dashboard.invalidate_recordset()
        self.assertEqual(dashboard.total_vehicles, before)
        self.assertEqual(dashboard.company_id, self.env.company)
        self.assertIn(dashboard, self.env['car.rental.dashboard'].search([('company_id', 'in', self.env.company.ids)]))
        self.assertFalse(self.env['car.rental.dashboard'].search([('company_id', '=', 0)]))

    def test_existing_booking_cleaning_fee_can_be_set_before_signature(self):
        rental = self.rental()
        self.rule.action_draft()
        self.rule.cleaning_fee = 40
        self.rule.action_approve()
        self.reservation.action_refresh_cleaning_fee()
        self.assertEqual(self.reservation.cleaning_fee, 40)
        rental.write({'agreement_signature': self.photo})
        rental.action_sign_agreement()
        with self.assertRaisesRegex(ValidationError, 'before signing'), self.cr.savepoint():
            self.reservation.action_refresh_cleaning_fee()
