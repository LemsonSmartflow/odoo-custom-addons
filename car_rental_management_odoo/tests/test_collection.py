from unittest.mock import patch
from odoo.exceptions import ValidationError
from .test_workflow import TestConnectedWorkflow


class TestCollection(TestConnectedWorkflow):
    def collection(self, rental, amount):
        return self.env['car.rental.collection'].create({'rental_id': rental.id, 'amount': amount,
                                                       'payment_method': 'bank_transfer', 'reference': 'BANK-TEST'})

    def test_full_collection_invoice_deposit_and_idempotence(self):
        rental = self.rental()
        wizard = self.collection(rental, 400)
        self.assertEqual(wizard.to_deposit, 100)
        self.assertEqual(wizard.to_rental, 300)
        wizard.action_post()
        self.assertEqual(rental.balance_due, 0)
        self.assertEqual(rental.deposit_held, 100)
        self.assertEqual(rental.invoice_ids.state, 'posted')
        self.assertEqual(rental.payment_ids.collection_reference, 'BANK-TEST')
        self.assertEqual(rental.deposit_transaction_ids.collection_method, 'bank_transfer')
        wizard.action_post()
        self.assertEqual(len(rental.payment_ids), 1)
        self.assertEqual(len(rental.deposit_transaction_ids), 1)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            rental.action_collect_payment()

    def test_partial_collection_and_minimum_then_remaining(self):
        rental = self.rental()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.collection(rental, 49).action_post()
        self.assertFalse(rental.invoice_ids)
        self.collection(rental, 50).action_post()
        self.assertEqual(rental.deposit_held, 50)
        self.assertEqual(rental.balance_due, 300)
        action = rental.action_collect_payment()
        defaults = self.env['car.rental.collection'].with_context(**action['context']).default_get(['rental_id','amount'])
        self.assertEqual(defaults['amount'], 350)
        self.collection(rental, 150).action_post()
        self.assertEqual(rental.deposit_held, 100)
        self.assertEqual(rental.balance_due, 200)
        self.collection(rental, 200).action_post()
        self.assertEqual(rental.balance_due, 0)

    def test_overpayment_and_changed_balance_blocked(self):
        rental = self.rental()
        stale = self.collection(rental, 400)
        self.collection(rental, 100).action_post()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            stale.action_post()
        self.assertEqual(rental.balance_due, 300)
        self.assertEqual(rental.deposit_held, 100)

    def test_failure_rolls_back_invoice_and_deposit(self):
        rental = self.rental()
        wizard = self.collection(rental, 400)
        with patch.object(type(self.env['car.rental.payment']), 'action_post_receipt', side_effect=ValidationError('Posting failed')):
            with self.assertRaises(ValidationError):
                wizard.action_post()
        rental.invalidate_recordset()
        self.assertFalse(rental.invoice_ids)
        self.assertFalse(rental.deposit_transaction_ids)
        self.assertFalse(rental.payment_ids)
        self.assertFalse(wizard.posted)
