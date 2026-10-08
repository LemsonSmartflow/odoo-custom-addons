# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class MaintenanceRequest(models.Model):
    _inherit = 'maintenance.request'

    rental_vehicle_id = fields.Many2one(
        'fleet.vehicle', string='Rental Vehicle', index='btree',
        help='Rental fleet vehicle this request relates to.')
