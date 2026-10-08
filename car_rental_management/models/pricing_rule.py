# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class CarRentalPricingRule(models.Model):
    _name = 'car.rental.pricing.rule'
    _description = 'Rental Pricing Rule'
    _inherit = ['mail.thread']
    _order = 'effective_from desc, min_days asc'
    _rec_names_search = ['name', 'destination_id.name', 'vehicle_category_id.name']

    name = fields.Char('Name', required=True, tracking=True)
    destination_id = fields.Many2one('car.rental.destination', string='Destination', required=True, ondelete='restrict')
    vehicle_category_id = fields.Many2one(
        'car.rental.vehicle.category', string='Vehicle Category', required=True, ondelete='restrict')
    min_days = fields.Integer(string='Minimum Days', required=True, default=1)
    max_days = fields.Integer(
        string='Maximum Days',
        help='Leave empty for an open-ended band (e.g. 31 days and more).')
    daily_rate = fields.Monetary(
        string='Daily Rate', required=True, currency_field='currency_id', tracking=True)
    currency_id = fields.Many2one('res.currency', string='Currency', required=True)
    effective_from = fields.Date(string='Effective From', required=True, default=fields.Date.today)
    effective_to = fields.Date(string='Effective To')
    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.company)
    active = fields.Boolean(default=True)
    notes = fields.Text(string='Notes')

    @api.constrains('min_days', 'max_days')
    def _check_days_range(self):
        for rule in self:
            if rule.min_days < 1:
                raise ValidationError(_('The minimum rental duration must be at least one day.'))
            if rule.max_days and rule.max_days < rule.min_days:
                raise ValidationError(_('The maximum rental duration cannot be lower than the minimum.'))

    @api.constrains('daily_rate')
    def _check_daily_rate(self):
        for rule in self:
            if rule.daily_rate < 0:
                raise ValidationError(_('The daily rate cannot be negative.'))

    @api.constrains('active', 'company_id', 'destination_id', 'vehicle_category_id', 'min_days', 'max_days', 'effective_from', 'effective_to')
    def _check_rule_overlap(self):
        for rule in self:
            if not rule.active:
                continue
            domain = [
                ('id', '!=', rule.id),
                ('active', '=', True),
                ('company_id', '=', rule.company_id.id),
                ('destination_id', '=', rule.destination_id.id),
                ('vehicle_category_id', '=', rule.vehicle_category_id.id),
                ('min_days', '<=', rule.max_days or 999999),
                '|', ('max_days', '=', False), ('max_days', '>=', rule.min_days),
            ]
            overlapping = self.search(domain)
            for other in overlapping:
                if self._rules_overlap(rule, other):
                    raise ValidationError(_(
                        'Pricing rule "%(rule)s" overlaps active rule "%(other)s" for destination '
                        '"%(destination)s", category "%(category)s" and the same duration range. '
                        'Overlapping rules are not allowed.',
                        rule=rule.name, other=other.name,
                        destination=rule.destination_id.name, category=rule.vehicle_category_id.name,
                    ))

    @staticmethod
    def _rules_overlap(rule_a, rule_b):
        overlap_dates = (
            (not rule_a.effective_to or rule_b.effective_from <= rule_a.effective_to)
            and (not rule_b.effective_to or rule_a.effective_from <= rule_b.effective_to)
        )
        if not overlap_dates:
            return False
        max_a = rule_a.max_days or 999999
        max_b = rule_b.max_days or 999999
        return rule_a.min_days <= max_b and rule_b.min_days <= max_a

    def _match_domain(self, company_id, vehicle_category_id, destination_id, rental_days, rental_date):
        return [
            ('active', '=', True),
            ('company_id', '=', company_id),
            ('vehicle_category_id', '=', vehicle_category_id),
            ('destination_id', '=', destination_id),
            ('min_days', '<=', rental_days),
            '|', ('max_days', '=', False), ('max_days', '>=', rental_days),
            ('effective_from', '<=', rental_date),
            '|', ('effective_to', '=', False), ('effective_to', '>=', rental_date),
        ]

    @api.model
    def find_matching_rule(self, company_id, vehicle_category_id, destination_id, rental_days, rental_date):
        """Return the applicable active rule or an empty recordset."""
        if not vehicle_category_id or not destination_id or not rental_date or not rental_days:
            return self.browse()
        return self.search(
            self._match_domain(company_id, vehicle_category_id, destination_id, rental_days, rental_date),
            limit=1,
        )

    @api.model
    def get_applicable_rate(self, company_id, vehicle_category_id, destination_id, rental_days, rental_date):
        """Return (rule, daily_rate) for the given rental context."""
        rule = self.find_matching_rule(company_id, vehicle_category_id, destination_id, rental_days, rental_date)
        return rule, rule.daily_rate if rule else 0.0
