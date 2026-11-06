from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    journeys = env['car.rental.journey'].search([])
    for journey in journeys:
        reservation = journey.reservation_id
        rental = reservation.rental_ids[:1]
        if journey.cancelled or (reservation and reservation.status == 'cancelled'):
            step = 'cancelled'
        elif rental and rental.status == 'closed':
            step = 'closed'
        elif rental and rental.status == 'returned':
            step = 'settlement'
        elif rental and rental.status == 'ongoing':
            step = 'return'
        elif rental and rental.agreement_state == 'signed':
            step = 'pickup' if not rental._journey_payment_blockers() else 'payment'
        elif rental:
            step = 'agreement'
        elif reservation:
            step = 'quote'
        else:
            step = 'booking'
        cr.execute(
            'UPDATE car_rental_journey SET step = %s WHERE id = %s',
            [step, journey.id],
        )
