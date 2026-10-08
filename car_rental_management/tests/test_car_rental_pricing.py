# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import common


class TestCarRentalPricing(common.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.category = cls.env['car.rental.vehicle.category'].create({
            'name': 'Test Category',
            'company_id': cls.env.company.id,
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Test Rental Product',
            'type': 'consu',
            'is_car_rental': True,
            'rental_vehicle_category_id': cls.category.id,
        })
        cls.category.rental_product_id = cls.product.id
        cls.destination_maun = cls.env['car.rental.destination'].create({
            'name': 'Test Maun', 'code': 'TMAUN', 'company_id': cls.env.company.id})
        cls.destination_gab = cls.env['car.rental.destination'].create({
            'name': 'Test Gaborone', 'code': 'TGBE', 'company_id': cls.env.company.id})
        cls.today = fields.Date.today()

    def _create_rule(self, destination, daily_rate, min_days=1, max_days=False, effective_from=False, effective_to=False, name=False):
        return self.env['car.rental.pricing.rule'].create({
            'name': name or 'Rule %s %s' % (destination.name, daily_rate),
            'destination_id': destination.id,
            'vehicle_category_id': self.category.id,
            'min_days': min_days,
            'max_days': max_days,
            'daily_rate': daily_rate,
            'currency_id': self.company.currency_id.id,
            'effective_from': effective_from or self.today,
            'effective_to': effective_to,
            'company_id': self.company.id,
        })

    def test_01_rule_matching_duration_bands(self):
        """AT-004: Book Maun rental - correct rate; duration bands respected."""
        self._create_rule(self.destination_maun, 550, min_days=1, max_days=3)
        self._create_rule(self.destination_maun, 500, min_days=4, max_days=7)
        rule = self.env['car.rental.pricing.rule'].find_matching_rule(
            self.company.id, self.category.id, self.destination_maun.id, 2, self.today)
        self.assertEqual(rule.daily_rate, 550)
        rule = self.env['car.rental.pricing.rule'].find_matching_rule(
            self.company.id, self.category.id, self.destination_maun.id, 5, self.today)
        self.assertEqual(rule.daily_rate, 500)
        rule = self.env['car.rental.pricing.rule'].find_matching_rule(
            self.company.id, self.category.id, self.destination_maun.id, 8, self.today)
        self.assertFalse(rule)

    def test_02_rule_effective_dates(self):
        """AT-003: Rule saved with effective dates; future rules not applicable yet."""
        future_date = fields.Date.add(self.today, days=30)
        self._create_rule(self.destination_maun, 550, effective_from=future_date)
        rule = self.env['car.rental.pricing.rule'].find_matching_rule(
            self.company.id, self.category.id, self.destination_maun.id, 2, self.today)
        self.assertFalse(rule)
        rule = self.env['car.rental.pricing.rule'].find_matching_rule(
            self.company.id, self.category.id, self.destination_maun.id, 2, future_date)
        self.assertEqual(rule.daily_rate, 550)

    def test_03_duplicate_rule_rejected(self):
        """AT-008: Overlapping active rules are rejected."""
        self._create_rule(self.destination_gab, 350, min_days=1, max_days=7)
        with self.assertRaises(ValidationError):
            self._create_rule(self.destination_gab, 400, min_days=5, max_days=10)

    def test_04_expired_rule_does_not_block_new_rule(self):
        """An expired rule does not conflict with a new rule for the same window."""
        past_rule = self._create_rule(
            self.destination_gab, 350, min_days=1, max_days=7,
            effective_from=fields.Date.add(self.today, days=-30),
            effective_to=fields.Date.add(self.today, days=-1))
        self.assertTrue(past_rule.active)
        new_rule = self._create_rule(self.destination_gab, 400, min_days=1, max_days=7)
        self.assertTrue(new_rule)

    def test_05_days_range_validation(self):
        with self.assertRaises(ValidationError):
            self._create_rule(self.destination_gab, 350, min_days=0)

    def test_06_rental_days_inclusive(self):
        """Rental days are inclusive of pickup and return day."""
        partner = self.env['res.partner'].create({'name': 'Pricing Customer'})
        order = self.env['sale.order'].create({
            'partner_id': partner.id,
            'rental_vehicle_category_id': self.category.id,
            'rental_destination_id': self.destination_maun.id,
            'rental_pickup_date': self.today,
            'rental_return_date': fields.Date.add(self.today, days=3),
        })
        self.assertEqual(order.rental_days, 4)
