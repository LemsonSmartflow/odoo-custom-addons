"""Configure rental accounting defaults on existing installations."""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    try:
        from odoo.addons.car_rental_management_odoo.hooks import (
            _ensure_rental_accounting,
        )
        _ensure_rental_accounting(env)
        env.cr.commit()
    except Exception as exc:  # pragma: no cover - defensive on legacy DBs
        _logger.warning('Could not configure rental accounts: %s', exc)
