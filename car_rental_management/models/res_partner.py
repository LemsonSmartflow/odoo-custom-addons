# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    driver_license_number = fields.Char(string='Driver Licence Number')
    driver_license_expiry = fields.Date(string='Driver Licence Expiry')
    id_number = fields.Char(
        string='ID / Passport Number',
        help='National identification or passport details where required.')
    emergency_contact_name = fields.Char(string='Emergency Contact')
    emergency_contact_phone = fields.Char(string='Emergency Contact Phone')
