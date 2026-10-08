# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models

DEPOSIT_METHODS = [
    ('none', 'No Deposit'),
    ('cash', 'Cash'),
    ('card', 'Card'),
    ('bank', 'Bank Transfer'),
    ('mobile', 'Mobile Money'),
]


class CarRentalVehicleCategory(models.Model):
    _name = 'car.rental.vehicle.category'
    _description = 'Rental Vehicle Category'
    _order = 'name asc'
    _rec_names_search = ['name']

    name = fields.Char('Name', required=True)
    active = fields.Boolean(default=True)
    description = fields.Text(string='Description')
    rental_product_id = fields.Many2one(
        'product.product', string='Rental Product',
        domain="[('type', '=', 'consu')]",
        help='Commercial rental product sold on rental orders for this vehicle class. '
             'One product per vehicle class, never one per physical vehicle.')
    deposit_method = fields.Selection(
        selection=DEPOSIT_METHODS, string='Deposit Method', default='card', required=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id')
    vehicle_count = fields.Integer(compute='_compute_vehicle_count', string='Vehicles')

    _name_company_uniq = models.Constraint(
        'UNIQUE (name, company_id)',
        'The vehicle category name must be unique per company.',
    )

    def _compute_vehicle_count(self):
        group = self.env['fleet.vehicle']._read_group(
            [('rental_category_id', 'in', self.ids)], ['rental_category_id'], aggregates=['__count'],
        )
        count_by_category = {rental_category.id: count for rental_category, count in group}
        for category in self:
            category.vehicle_count = count_by_category.get(category.id, 0)
