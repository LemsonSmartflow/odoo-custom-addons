import base64

from odoo.tools import file_open


def _fill_template(template, env):
    from .models.rental_agreement import AGREEMENT_FIELD_TOKENS
    if not template.master_pdf:
        with file_open(
            'car_rental_management_odoo/data/city_delights_contract.pdf', 'rb'
        ) as source:
            template.master_pdf = base64.b64encode(source.read())
    if not template.master_filename:
        template.master_filename = 'City Delights Contract.pdf'
    if not template.field_ids:
        fields = env['rental.agreement.template.field'].sudo()
        for sequence, (key, label, section) in enumerate(AGREEMENT_FIELD_TOKENS):
            fields.create({
                'template_id': template.id,
                'sequence': sequence * 10,
                'key': key,
                'label': label,
                'section': section,
                'required': key in ('renter_name', 'identity_number', 'vehicle_registration',
                                    'delivery_date', 'lease_period', 'delivery_place',
                                    'security_deposit', 'daily_rental'),
            })
    if template.state != 'active':
        template.action_activate()


def _seed_default_template(env):
    """Create (or repair) the City Delights master template per company."""
    Template = env['rental.agreement.template'].sudo()
    for company in env['res.company'].search([]):
        template = Template.search([
            ('company_id', '=', company.id)], limit=1)
        if not template:
            template = Template.create({
                'name': 'City Delights Standard Rental Agreement',
                'company_id': company.id,
                'version': 'City Delights supplied contract - October 2026',
                'state': 'draft',
                'is_default': True,
            })
        _fill_template(template, env)


def post_init_hook(env):
    service_types = env['fleet.service.type'].sudo()
    for name in ('Insurance', 'Road Licence', 'Fitness Certificate'):
        if not service_types.search([('category', '=', 'contract'), ('name', '=', name)], limit=1):
            service_types.create({'name': name, 'category': 'contract'})
    _seed_default_template(env)
