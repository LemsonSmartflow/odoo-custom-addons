# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import _, api, fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    is_car_rental = fields.Boolean(
        string='Car Rental',
        help='Mark this product as a rental product. One commercial rental product '
             'per vehicle class; the physical vehicle is a separate Fleet record.')
    rental_vehicle_category_id = fields.Many2one(
        'car.rental.vehicle.category', string='Rental Vehicle Category')

    @api.onchange('is_car_rental')
    def _onchange_is_car_rental(self):
        if not self.is_car_rental:
            self.rental_vehicle_category_id = False

    @api.onchange('rental_vehicle_category_id')
    def _onchange_rental_vehicle_category(self):
        if self.rental_vehicle_category_id and not self.is_car_rental:
            self.is_car_rental = True
        if self.rental_vehicle_category_id and not self.name:
            self.name = _('%s Rental', self.rental_vehicle_category_id.name)


class ProductProduct(models.Model):
    _inherit = 'product.product'
