from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestConnectedWorkflow(TransactionCase):
    def setUp(self):
        super().setUp()
        self.customer = self.env['car.rental.customer'].create({
            'first_name': 'Workflow', 'last_name': 'Test', 'cin': 'TEST-ID',
            'driving_license': 'TEST-LICENCE',
            'license_expiry': fields.Date.today() + timedelta(days=365),
        })
        self.vehicle = self.env['car.rental.vehicle'].create({
            'registration_number': 'WORKFLOW-TEST', 'brand': 'Test', 'model': 'Car',
            'daily_price': 100, 'mileage': 1000,
        })
        today = fields.Date.today()
        self.reservation = self.env['car.rental.reservation'].create({
            'customer_id': self.customer.id, 'vehicle_id': self.vehicle.id,
            'start_date': today, 'end_date': today + timedelta(days=3),
        })

    def rental(self):
        self.reservation.action_confirm()
        action = self.reservation.action_create_rental()
        return self.env['car.rental.rental'].browse(action['res_id'])

    def payment(self, rental, amount):
        return self.env['car.rental.payment'].create({
            'rental_id': rental.id, 'paid_amount': amount, 'payment_method': 'cash',
        })

    def test_reservation_creates_one_linked_rental(self):
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.reservation.action_create_rental()
        rental = self.rental()
        self.assertEqual(self.reservation.action_create_rental()['res_id'], rental.id)
        self.assertEqual(rental.initial_mileage, 1000)
        self.assertEqual(rental.amount, 300)
        self.assertTrue(self.reservation.reference.startswith('RES/'))
        self.assertTrue(rental.reference.startswith('RENT/'))
        self.assertEqual(self.customer.rental_count, 1)
        self.assertEqual(self.vehicle.rental_count, 1)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['car.rental.rental'].create({'reservation_id': self.reservation.id})

    def test_instalments_share_balance_and_status(self):
        rental = self.rental()
        first = self.payment(rental, 100)
        self.assertEqual(rental.paid_total, 100)
        self.assertEqual(rental.balance_due, 200)
        self.assertEqual(first.remaining_amount, 200)
        self.assertEqual(first.status, 'partial')
        action = rental.action_record_payment()
        self.assertEqual(action['context']['default_rental_id'], rental.id)
        self.assertEqual(action['context']['default_paid_amount'], 200)
        second = self.payment(rental, 200)
        self.assertEqual(rental.payment_status, 'paid')
        self.assertEqual(rental.balance_due, 0)
        self.assertEqual(first.remaining_amount, 0)
        self.assertEqual(first.status, 'paid')
        self.assertTrue(second.reference.startswith('PAY/'))
        with self.assertRaises(ValidationError), self.cr.savepoint():
            rental.action_record_payment()
        second.unlink()
        self.assertEqual(rental.balance_due, 200)
        self.assertEqual(first.status, 'partial')
        first.paid_amount = 50
        self.assertEqual(rental.balance_due, 250)

    def test_combined_overpayment_is_rejected(self):
        rental = self.rental()
        first = self.payment(rental, 200)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.payment(rental, 150)
        self.assertEqual(rental.balance_due, 100)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            first.paid_amount = 301
        for amount in (0, -1):
            with self.assertRaises(ValidationError), self.cr.savepoint():
                self.payment(rental, amount)

    def test_pickup_return_updates_vehicle(self):
        rental = self.rental()
        self.payment(rental, 100)
        rental.action_start_rental()
        self.assertEqual(self.vehicle.status, 'rented')
        with self.assertRaises(ValidationError), self.cr.savepoint():
            rental.action_start_rental()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            rental.action_return_vehicle()
        rental.final_mileage = 1200
        rental.action_return_vehicle()
        self.assertEqual(self.vehicle.status, 'available')
        self.assertEqual(self.vehicle.mileage, 1200)
        self.assertEqual(rental.balance_due, 200)
        self.payment(rental, 200)
        self.assertEqual(rental.payment_status, 'paid')

    def test_linked_reservation_is_protected(self):
        self.rental()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.reservation.action_cancel()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.reservation.end_date += timedelta(days=1)

    def test_navigation_and_views(self):
        rental = self.rental()
        payment = self.payment(rental, 100)
        self.assertEqual(payment.action_rental()['res_id'], rental.id)
        self.assertEqual(rental.action_reservation()['res_id'], self.reservation.id)
        self.assertEqual(self.vehicle.action_book()['context']['default_vehicle_id'], self.vehicle.id)
        self.assertEqual(self.customer.action_book()['context']['default_customer_id'], self.customer.id)
        for model, types in {
            'car.rental.vehicle': ['kanban', 'form', 'list'],
            'car.rental.reservation': ['form', 'list'],
            'car.rental.rental': ['form', 'list', 'search'],
            'car.rental.payment': ['form'],
            'car.rental.customer': ['form'],
            'car.rental.dashboard': ['form'],
        }.items():
            for view_type in types:
                self.assertTrue(self.env[model].get_view(view_type=view_type)['arch'])
