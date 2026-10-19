"""Booking journey progression and financial handoff against the resumable workspace."""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged

from .common import RentalTestCommon


@tagged('post_install', '-at_install')
class TestBookingJourney(RentalTestCommon):

    # ── helpers ──────────────────────────────────────────────────────────────
    def _journey(self, record):
        action = record.action_booking_journey()
        return self.env['car.rental.journey'].browse(action['res_id'])

    def _collect_payment(self, rental, amount=None):
        """Post the combined collection: rental invoice, payment and deposit."""
        if amount is None:
            amount = rental.balance_due + max(rental.deposit_required - rental.deposit_collected, 0.0)
        wizard = self.env['car.rental.collection'].create({
            'rental_id': rental.id, 'amount': amount,
            'payment_method': 'bank_transfer', 'reference': 'BANK-JOURNEY'})
        wizard.action_post()
        return wizard

    def _refund_deposit(self, rental):
        deposit = self.env['car.rental.deposit.transaction'].create({
            'rental_id': rental.id, 'kind': 'refund', 'amount': rental.deposit_held})
        deposit.action_post()
        return deposit

    # ── tests ───────────────────────────────────────────────────────────────
    def test_staff_journey_and_financial_handoff(self):
        rental = self._make_rental(self._make_reservation())
        action = rental.with_user(self.user_agent).action_booking_journey()
        journey = self.env['car.rental.journey'].with_user(self.user_agent).browse(action['res_id'])
        self.assertEqual(journey.step, 'agreement')
        with self.assertRaises(AccessError), self.cr.savepoint():
            rental.with_user(self.user_agent).action_close_journey()

    def test_dirty_return_cannot_close_without_cleaning_settlement(self):
        reservation = self._make_reservation(cleaning_fee=30.0)
        rental = self._ready_to_handover(reservation)
        self._collect_payment(rental)
        rental.action_start_rental()
        self._complete_return_inspection(rental, clean='no')
        rental.action_return_vehicle()
        self.assertIn('Create and post the cleaning invoice.', rental._journey_close_blockers())
        with self.assertRaises(ValidationError), self.cr.savepoint():
            rental.action_close_journey()

    def test_saved_journey_quote_confirm_and_resume(self):
        partner = self._make_partner()
        vehicle = self._make_vehicle()
        zone = self._make_zone()
        self._make_rate_rule(vehicle.rental_category_id, zone)
        start = (fields.Datetime.now() + timedelta(days=1)).replace(
            hour=8, minute=0, second=0, microsecond=0)
        journey = self.env['car.rental.journey'].create({'partner_id': partner.id})
        self.assertEqual(journey.step, 'customer')
        journey.action_continue()
        journey.write({
            'destination_id': zone.id, 'category_id': vehicle.rental_category_id.id,
            'pickup_datetime': start, 'expected_return_datetime': start + timedelta(days=3)})
        journey.action_continue()
        journey.invalidate_recordset()
        self.assertEqual(journey.step, 'quote')
        self.assertEqual(journey.deposit_required, 100)
        journey.action_continue()
        journey.invalidate_recordset()
        self.assertEqual(journey.step, 'confirm')
        journey.action_continue()
        journey.invalidate_recordset()
        self.assertEqual(journey.step, 'agreement')
        self.assertEqual(journey.reservation_id.action_booking_journey()['res_id'], journey.id)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            journey.action_collect_payment()

    def test_agreement_before_payment_and_pickup(self):
        rental = self._make_rental(self._make_reservation())
        journey = self._journey(rental)
        self.assertEqual(journey.step, 'agreement')
        with self.assertRaises(ValidationError), self.cr.savepoint():
            journey.action_collect_payment()
        self._sign_agreement(rental)
        journey.invalidate_recordset()
        self.assertEqual(journey.step, 'payment')
        self.assertEqual(journey.action_collect_payment()['res_model'], 'car.rental.collection')
        self._collect_payment(rental)
        journey.invalidate_recordset()
        self.assertEqual(journey.step, 'pickup')
        self._complete_pickup_inspection(rental)
        journey.invalidate_recordset()
        self.assertEqual(journey.step, 'handover')

    def test_return_settlement_and_close(self):
        rental = self._ready_to_handover()
        journey = self._journey(rental)
        self._collect_payment(rental)
        journey.invalidate_recordset()
        self.assertEqual(journey.step, 'handover')
        journey.action_continue()
        journey.invalidate_recordset()
        self.assertEqual(journey.step, 'return')
        with self.assertRaises(ValidationError), self.cr.savepoint():
            rental.action_close_journey()
        self._complete_return_inspection(rental)
        journey.action_continue()
        journey.invalidate_recordset()
        self.assertEqual(journey.step, 'settlement')
        with self.assertRaises(ValidationError), self.cr.savepoint():
            journey.action_continue()
        self._refund_deposit(rental)
        journey.action_continue()
        journey.invalidate_recordset()
        self.assertEqual(journey.step, 'closed')
        self.assertTrue(rental.closed_on)

    def test_cancelled_journey_and_partial_payment(self):
        reservation = self._make_reservation()
        journey = self._journey(reservation)
        reservation.action_cancel()
        journey.invalidate_recordset()
        self.assertEqual(journey.step, 'cancelled')
        reservation.action_reset_draft()
        reservation.action_confirm()
        rental = self._make_rental(reservation)
        self.company.rental_require_full_payment = True
        self._collect_payment(rental, rental.deposit_required + 50.0)
        self.assertIn('Settle the rental payment required before pickup.',
                      rental._journey_payment_blockers())

    def test_cancel_booking_releases_vehicle_and_retains_history(self):
        reservation = self._make_reservation()
        rental = self._make_rental(reservation)
        journey = self._journey(rental)
        journey.action_cancel()
        self.assertEqual(reservation.status, 'cancelled')
        self.assertEqual(rental.status, 'cancelled')
        self.assertEqual(journey.step, 'cancelled')
        self.assertEqual(rental.vehicle_id.rental_status, 'available')
        with self.assertRaises(ValidationError):
            journey.unlink()
        with self.assertRaises(ValidationError):
            rental.action_start_rental()

    def test_cancel_and_delete_unlinked_booking(self):
        journey = self.env['car.rental.journey'].create({})
        journey.action_cancel()
        self.assertEqual(journey.step, 'cancelled')
        journey.unlink()
        self.assertFalse(journey.exists())

    def test_financial_booking_cannot_be_erased_by_cancellation(self):
        rental = self._make_rental(self._make_reservation())
        self._collect_deposit(rental)
        journey = self._journey(rental)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            journey.action_cancel()
        self.assertEqual(rental.status, 'draft')
        self.assertGreater(rental.deposit_held, 0)

    def test_ongoing_booking_uses_return_inspection(self):
        rental = self._ready_to_handover()
        self._collect_payment(rental)
        rental.action_start_rental()
        journey = self._journey(rental)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            journey.action_cancel()
        self.assertEqual(rental.status, 'ongoing')
        action = journey.action_end_early()
        self.assertEqual(action['res_model'], 'car.rental.check')
        self.assertEqual(action['context']['default_kind'], 'return')
        self._complete_return_inspection(rental)
        journey.action_continue()
        self.assertEqual(rental.status, 'returned')
        self.assertEqual(journey.step, 'settlement')

    def test_agent_can_delete_an_unused_booking(self):
        journey = self.env['car.rental.journey'].with_user(self.user_agent).create({})
        journey.unlink()
        self.assertFalse(journey.exists())
