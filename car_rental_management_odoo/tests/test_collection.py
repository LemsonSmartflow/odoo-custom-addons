"""Combined collection tests: rental invoice, security deposit and native payment."""
from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import RentalTestCommon


@tagged('post_install', '-at_install')
class TestCollection(RentalTestCommon):

    # ── helpers ──────────────────────────────────────────────────────────────
    def _collection(self, rental, amount):
        return self.env['car.rental.collection'].create({
            'rental_id': rental.id, 'amount': amount,
            'payment_method': 'bank_transfer', 'reference': 'BANK-TEST'})

    def _payments(self, rental):
        return self.env['account.payment'].search([('car_rental_id', '=', rental.id)])

    def _open_rental(self):
        return self._make_rental(self._make_reservation())

    # ── tests ───────────────────────────────────────────────────────────────
    def test_full_collection_invoice_deposit_and_idempotence(self):
        rental = self._open_rental()
        wizard = self._collection(rental, rental.amount + rental.deposit_required)
        self.assertEqual(wizard.to_deposit, rental.deposit_required)
        self.assertEqual(wizard.to_rental, rental.amount)
        wizard.action_post()
        self.assertEqual(rental.balance_due, 0)
        self.assertEqual(rental.paid_total, rental.amount)
        self.assertEqual(rental.payment_status, 'paid')
        self.assertEqual(rental.deposit_held, rental.deposit_required)
        self.assertEqual(rental.invoice_ids.mapped('state'), ['posted'])
        self.assertEqual(rental.deposit_transaction_ids.mapped('collection_method'), ['bank_transfer'])
        payments = self._payments(rental)
        self.assertEqual(len(payments), 1)
        self.assertEqual(payments.collection_reference, 'BANK-TEST')
        wizard.action_post()
        self.assertEqual(len(self._payments(rental)), 1)
        self.assertEqual(len(rental.deposit_transaction_ids), 1)
        self.assertEqual(len(rental.invoice_ids), 1)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            rental.action_collect_payment()

    def test_partial_collection_and_minimum_then_remaining(self):
        rental = self._open_rental()
        minimum = rental.reservation_id.quoted_daily_rate * 0.5
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self._collection(rental, minimum - 1).action_post()
        self.assertFalse(rental.invoice_ids)
        self._collection(rental, minimum).action_post()
        self.assertEqual(rental.deposit_held, minimum)
        self.assertEqual(rental.balance_due, rental.amount)
        self.assertEqual(rental.payment_status, 'unpaid')
        action = rental.action_collect_payment()
        defaults = self.env['car.rental.collection'].with_context(
            **action['context']).default_get(['rental_id', 'amount'])
        self.assertEqual(defaults['amount'], rental.amount + rental.deposit_required - minimum)
        self._collection(rental, minimum + 100).action_post()
        self.assertEqual(rental.deposit_held, rental.deposit_required)
        self.assertEqual(rental.balance_due, rental.amount - 100)
        self._collection(rental, rental.balance_due).action_post()
        self.assertEqual(rental.balance_due, 0)
        self.assertEqual(rental.payment_status, 'paid')

    def test_overpayment_and_changed_balance_blocked(self):
        rental = self._open_rental()
        stale = self._collection(rental, rental.amount + rental.deposit_required)
        self._collection(rental, rental.deposit_required).action_post()
        self.assertEqual(rental.balance_due, rental.amount)
        self.assertEqual(rental.deposit_held, rental.deposit_required)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            stale.action_post()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self._collection(rental, rental.balance_due + 1).action_post()
        self.assertEqual(rental.balance_due, rental.amount)
        self.assertEqual(rental.deposit_held, rental.deposit_required)
        self.assertEqual(len(rental.invoice_ids), 1)

    def test_failure_rolls_back_invoice_and_deposit(self):
        rental = self._open_rental()
        wizard = self._collection(rental, rental.amount + rental.deposit_required)
        with patch.object(type(self.env['account.payment']), 'action_post',
                          side_effect=ValidationError('Posting failed')):
            with self.assertRaises(ValidationError):
                wizard.action_post()
        rental.invalidate_recordset()
        wizard.invalidate_recordset()
        self.assertFalse(rental.invoice_ids)
        self.assertFalse(rental.deposit_transaction_ids)
        self.assertFalse(self._payments(rental))
        self.assertFalse(wizard.posted)
