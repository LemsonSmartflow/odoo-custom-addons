# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class CarRentalDestination(models.Model):
    _name = 'car.rental.destination'
    _description = 'Rental Destination'
    _order = 'name asc'
    _rec_names_search = ['name', 'code']

    name = fields.Char('Name', required=True)
    code = fields.Char('Code', required=True)
    region_id = fields.Many2one('res.country.state', string='Region')
    active = fields.Boolean(default=True)
    delivery_fee = fields.Monetary(
        string='Delivery Fee', currency_field='currency_id',
        help='Additional fee charged when the vehicle is delivered to this destination.')
    return_fee = fields.Monetary(
        string='Return Fee', currency_field='currency_id',
        help='Additional fee charged when the vehicle is returned to this destination.')
    is_cross_border = fields.Boolean(string='Cross Border')
    approval_required = fields.Boolean(
        string='Approval Required', default=True,
        help='Bookings to this destination require manager approval before confirmation.')
    notes = fields.Text(string='Notes')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id')

    _code_company_uniq = models.Constraint(
        'UNIQUE (code, company_id)',
        'The destination code must be unique per company.',
    )

    @api.constrains('code')
    def _check_code_format(self):
        for destination in self:
            if destination.code and not destination.code.strip():
                raise ValidationError(_('The destination code cannot be blank.'))
