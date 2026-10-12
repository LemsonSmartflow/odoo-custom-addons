from odoo import api, SUPERUSER_ID, fields
from odoo.addons.car_rental_management_odoo.models.business_rules import monthly_reference


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    for model, prefix in [('car.rental.reservation', 'RES'), ('car.rental.rental', 'REN')]:
        records = env[model].search(['|', ('reference', '=', False), ('reference', '=ilike', 'New')], order='pickup_datetime, id')
        for record in records:
            date = record.pickup_datetime.date() if record.pickup_datetime else record.start_date or fields.Date.today()
            record.reference = monthly_reference(env, model, prefix, record.company_id, date)
