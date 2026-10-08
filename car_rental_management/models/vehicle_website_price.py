# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models


class VehicleWebsitePrice(models.Model):
    _name = 'vehicle.website.price'
    _description = 'Vehicle Website Pricing Display'
    _order = 'destination_id, min_days'

    vehicle_id = fields.Many2one('fleet.vehicle', string='Vehicle', required=True, ondelete='cascade')
    destination_id = fields.Many2one('car.rental.destination', string='Destination', required=True)
    min_days = fields.Integer(string='Min Days', required=True, default=1)
    max_days = fields.Integer(string='Max Days', help='0 = no upper limit')
    daily_rate = fields.Float(string='Daily Rate', required=True)
    currency_id = fields.Many2one('res.currency', string='Currency',
                                  default=lambda self: self.env.company.currency_id)
    total_price = fields.Float(string='Total Price', compute='_compute_total', store=True)
    price_display = fields.Char(string='Price Display', compute='_compute_price_display')

    @api.depends('daily_rate', 'min_days', 'max_days')
    def _compute_total(self):
        for price in self:
            days = price.max_days if price.max_days else price.min_days
            price.total_price = price.daily_rate * max(days, 1)

    @api.depends('daily_rate', 'min_days', 'max_days', 'currency_id')
    def _compute_price_display(self):
        for price in self:
            if price.max_days:
                price.price_display = '%s %s/day (%d-%d days)' % (
                    price.currency_id.symbol or 'P', price.daily_rate,
                    price.min_days, price.max_days)
            else:
                price.price_display = '%s %s/day (%d+ days)' % (
                    price.currency_id.symbol or 'P', price.daily_rate, price.min_days)
