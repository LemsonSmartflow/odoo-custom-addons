from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from .test_workflow import TestConnectedWorkflow


class TestBookingJourney(TestConnectedWorkflow):
    def test_staff_journey_and_financial_handoff(self):
        staff = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Journey Staff', 'login': 'journey-staff', 'company_id': self.env.company.id,
            'company_ids': [fields.Command.set(self.env.company.ids)],
            'group_ids': [fields.Command.set([self.env.ref('base.group_user').id,
                                            self.env.ref('car_rental_management_odoo.group_car_rental_agent').id])]})
        rental = self.rental()
        action = rental.with_user(staff).action_booking_journey()
        journey = self.env['car.rental.journey'].with_user(staff).browse(action['res_id'])
        self.assertEqual(journey.step, 'payment')
        with self.assertRaises(AccessError), self.cr.savepoint():
            rental.with_user(staff).action_close_journey()

    def test_dirty_return_cannot_close_without_cleaning_settlement(self):
        self.rule.action_draft()
        self.rule.write({'cleaning_fee': 30})
        self.rule.action_approve()
        self.reservation.action_reprice()
        rental = self.rental()
        self.payment(rental, rental.amount)
        self.handover(rental)
        self.inspection(rental, 'return', 1050, clean='no')
        rental.action_return_vehicle()
        self.assertIn('Create and post the cleaning invoice.', rental._journey_close_blockers())
        with self.assertRaises(ValidationError), self.cr.savepoint():
            rental.action_close_journey()

    def test_saved_journey_quote_confirm_and_resume(self):
        self.reservation.action_cancel()
        journey = self.env['car.rental.journey'].create({'customer_id': self.customer.id})
        self.assertEqual(journey.step, 'customer')
        journey.action_continue()
        journey.write({'destination_id': self.destination.id, 'category_id': self.category.id,
                       'pickup_datetime': self.reservation.pickup_datetime,
                       'expected_return_datetime': self.reservation.expected_return_datetime})
        journey.action_continue()
        journey.invalidate_recordset()
        self.assertEqual(journey.step, 'quote')
        self.assertEqual(journey.deposit_required, 100)
        journey.action_continue()
        journey.invalidate_recordset()
        self.assertEqual(journey.step, 'confirm')
        journey.action_continue()
        journey.invalidate_recordset()
        self.assertEqual(journey.step, 'payment')
        self.assertEqual(journey.reservation_id.action_booking_journey()['res_id'], journey.id)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            journey.action_continue()

    def test_return_settlement_and_close(self):
        rental = self.rental()
        journey = self.env['car.rental.journey'].browse(rental.action_booking_journey()['res_id'])
        self.payment(rental, rental.amount)
        self.handover(rental)
        journey.invalidate_recordset()
        self.assertEqual(journey.step, 'return')
        with self.assertRaises(ValidationError), self.cr.savepoint():
            rental.action_close_journey()
        self.inspection(rental, 'return', 1050)
        journey.action_continue()
        journey.invalidate_recordset()
        self.assertEqual(journey.step, 'settlement')
        with self.assertRaises(ValidationError), self.cr.savepoint():
            journey.action_continue()
        self.deposit(rental, 'refund', rental.deposit_held)
        journey.action_continue()
        journey.invalidate_recordset()
        self.assertEqual(journey.step, 'closed')
        self.assertTrue(rental.closed_on)

    def test_cancelled_journey_and_partial_payment(self):
        journey = self.env['car.rental.journey'].browse(self.reservation.action_booking_journey()['res_id'])
        self.reservation.action_cancel()
        journey.invalidate_recordset()
        self.assertEqual(journey.step, 'cancelled')
        self.reservation.action_reset_draft()
        rental = self.rental()
        self.env.company.rental_require_full_payment = True
        self.payment(rental, 50)
        self.deposit(rental, 'collect', rental.deposit_required)
        self.assertIn('Settle the rental payment required before pickup.', rental._journey_payment_blockers())
