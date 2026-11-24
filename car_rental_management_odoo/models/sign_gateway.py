"""Optional Odoo Sign bridge.

Core never imports ``odoo.addons.sign`` and never declares a sign.* field, so
this module installs on Community.  An optional companion addon overrides this
gateway when Odoo Sign (Enterprise) is available.
"""
from odoo import api, models
from odoo.exceptions import UserError


class SignGateway(models.Model):
    _name = 'car.rental.sign.gateway'
    _description = 'Rental Agreement Signing Gateway'
    _auto = False

    @api.model
    def is_ready(self):
        """True only when the optional Odoo Sign bridge is installed."""
        return False

    @api.model
    def prepare(self, contract):
        raise UserError('The Odoo Sign bridge is not installed. Private signing links are used instead.')

    @api.model
    def send(self, contract):
        raise UserError('The Odoo Sign bridge is not installed. Private signing links are used instead.')

    @api.model
    def sync(self, contract):
        return False

    @api.model
    def cancel(self, contract):
        return False
