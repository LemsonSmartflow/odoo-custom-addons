"""Seed the first-class agreement template and facade records on upgrade."""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    try:
        from odoo.addons.car_rental_management_odoo.hooks import _seed_default_template
        _seed_default_template(env)
    except Exception as exc:  # pragma: no cover - defensive on legacy DBs
        _logger.warning('Could not seed rental agreement templates: %s', exc)

    Agreement = env['rental.agreement'].sudo()
    for contract in env['car.rental.contract'].search([]):
        if Agreement.search_count([('contract_id', '=', contract.id)]):
            continue
        company = contract.company_id
        template = env['rental.agreement.template'].sudo().search([
            ('company_id', '=', company.id)], limit=1)
        try:
            Agreement.create({
                'contract_id': contract.id,
                'rental_id': contract.rental_id.id,
                'template_id': template.id if template else False,
                'template_version_snapshot': contract.template_version,
                'template_master_hash': contract.source_hash,
                'is_legacy': True,
            })
        except Exception as exc:  # pragma: no cover
            _logger.warning('Could not migrate contract %s: %s', contract.id, exc)
