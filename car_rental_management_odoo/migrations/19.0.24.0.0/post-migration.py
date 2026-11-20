"""Give legacy reservations without a journey one, so every path is visible in Bookings."""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID
    env = api.Environment(cr, SUPERUSER_ID, {})
    reservations = env['car.rental.reservation'].search([])
    created = 0
    for reservation in reservations:
        if env['car.rental.journey'].search_count(
                [('reservation_id', '=', reservation.id)]):
            continue
        try:
            reservation._get_or_create_journey()
            created += 1
        except Exception as exc:  # pragma: no cover - defensive on legacy data
            _logger.warning('Could not create journey for reservation %s: %s',
                            reservation.reference, exc)
    _logger.info('Car Rental backfill created %s booking journeys', created)
