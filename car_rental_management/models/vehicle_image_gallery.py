# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class VehicleImageGallery(models.Model):
    _name = 'vehicle.image.gallery'
    _description = 'Vehicle Photo Gallery'
    _order = 'sequence, id'

    vehicle_id = fields.Many2one('fleet.vehicle', string='Vehicle', required=True, ondelete='cascade')
    image = fields.Image('Photo', max_width=1920, max_height=1920, required=True)
    image_128 = fields.Image('Thumbnail', related='image', max_width=128, max_height=128)
    sequence = fields.Integer(string='Sequence', default=10)
    is_primary = fields.Boolean(string='Primary Photo', default=False)
    name = fields.Char(string='Description')
