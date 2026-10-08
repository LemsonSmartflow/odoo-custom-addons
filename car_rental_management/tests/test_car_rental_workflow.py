# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import common, new_test_user


class TestCarRentalWorkflow(common.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.company if hasattr(cls, 'company') else cls.env.company
        cls.company = cls.env.company
        cls.staff_user = new_test_user(cls.env, 'rental staff user', groups='car_rental_management.car_rental_group_staff')
        cls.manager_user = new_test_user(cls.env, 'rental manager user', groups='car_rental_management.car_rental_group_manager')

        cls.category = cls.env['car.rental.vehicle.category'].create({
            'name': 'Workflow Category',
            'company_id': cls.env.company.id,
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Workflow Rental Product',
            'type': 'consu',
            'is_car_rental': True,
            'rental_vehicle_category_id': cls.category.id,
        })
        cls.category.rental_product_id = cls.product.id
        cls.destination = cls.env['car.rental.destination'].create({
            'name': 'Workflow Maun', 'code': 'WMAUN', 'company_id': cls.env.company.id})
        cls.pricing = cls.env['car.rental.pricing.rule'].create({
            'name': 'Workflow Maun Rule',
            'destination_id': cls.destination.id,
            'vehicle_category_id': cls.category.id,
            'min_days': 1,
            'max_days': 30,
            'daily_rate': 500,
            'currency_id': cls.env.company.currency_id.id,
            'effective_from': fields.Date.add(fields.Date.today(), days=-30),
            'company_id': cls.env.company.id,
        })
        cls.brand = cls.env['fleet.vehicle.model.brand'].create({'name': 'Test Brand'})
        cls.model = cls.env['fleet.vehicle.model'].create({
            'name': 'Test Model', 'brand_id': cls.brand.id, 'vehicle_type': 'car'})
        cls.bank_account = cls.env['account.account'].create({
            'name': 'Test Bank', 'code': 'T1005', 'account_type': 'asset_current'})
        cls.deposit_liability = cls.env['account.account'].create({
            'name': 'Test Deposits', 'code': 'T2105', 'account_type': 'liability_current'})
        cls.recovery_income = cls.env['account.account'].create({
            'name': 'Test Recovery', 'code': 'T4105', 'account_type': 'income'})
        cls.journal = cls.env['account.journal'].create({
            'name': 'Test Bank Journal', 'code': 'TBNK', 'type': 'bank',
            'default_account_id': cls.bank_account.id})
        cls.sale_journal = cls.env['account.journal'].create({
            'name': 'Test Sale Journal', 'code': 'TSALE', 'type': 'sale'})
        cls.receivable_account = cls.env['account.account'].create({
            'name': 'Test Receivable', 'code': 'T1100', 'account_type': 'asset_receivable',
            'reconcile': True})
        cls.company.write({
            'rental_deposit_liability_account_id': cls.deposit_liability.id,
            'rental_recovery_income_account_id': cls.recovery_income.id,
            'rental_deposit_journal_id': cls.journal.id,
        })
        cls.vehicle = cls.env['fleet.vehicle'].create({
            'model_id': cls.model.id,
            'license_plate': 'TEST-001',
            'rental_fleet_id': 'TEST-001',
            'rental_category_id': cls.category.id,
            'rental_status': 'available',
            'tracker_installed': True,
            'tracker_status': 'working',
        })
        cls.customer = cls.env['res.partner'].create({
            'name': 'Workflow Customer',
            'property_account_receivable_id': cls.receivable_account.id,
        })
        cls.today = fields.Date.today()

    def _create_order(self, pickup_offset=0, return_offset=3, vehicle=None):
        return self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'rental_vehicle_category_id': self.category.id,
            'rental_destination_id': self.destination.id,
            'rental_pickup_date': fields.Date.add(self.today, days=pickup_offset),
            'rental_return_date': fields.Date.add(self.today, days=return_offset),
            'allocated_vehicle_id': (vehicle or self.vehicle).id,
        })

    def test_01_confirm_reserves_vehicle(self):
        """AT-010: Confirm booking - vehicle becomes Reserved."""
        order = self._create_order()
        order.action_confirm_rental()
        self.assertEqual(order.rental_state, 'confirmed')
        self.assertEqual(order.allocated_vehicle_id.rental_status, 'reserved')
        self.assertTrue(order.pricing_rule_id)
        self.assertEqual(order.rental_daily_rate, 500)

    def test_02_no_rule_blocks_confirmation(self):
        """AT-007: No rate - confirmation blocked."""
        other_destination = self.env['car.rental.destination'].create({'name': 'No Rate', 'code': 'NORATE'})
        order = self._create_order()
        order.rental_destination_id = other_destination.id
        with self.assertRaises(UserError):
            order.action_confirm_rental()

    def test_03_deposit_equals_one_day(self):
        """AT-005: Deposit equals one applicable rental day."""
        order = self._create_order()
        order.action_confirm_rental()
        self.assertEqual(order.security_deposit_amount, 500)
        deposit = order.deposit_ids[:1]
        self.assertTrue(deposit)
        self.assertEqual(deposit.amount, 500)
        self.assertEqual(deposit.status, 'required')

    def test_04_double_booking_rejected(self):
        """AT-009: Double booking is rejected."""
        order1 = self._create_order()
        order1.action_confirm_rental()
        other_vehicle = self.env['fleet.vehicle'].create({
            'model_id': self.model.id,
            'license_plate': 'TEST-002',
            'rental_fleet_id': 'TEST-002',
            'rental_category_id': self.category.id,
            'rental_status': 'available',
        })
        order2 = self._create_order(vehicle=other_vehicle)
        order2.action_confirm_rental()
        with self.assertRaises(UserError):
            order2.allocated_vehicle_id = self.vehicle.id
            order2.action_allocate_vehicle()

    def test_05_rate_snapshot_on_confirm(self):
        """AT-020: Confirmed order retains the rate used at confirmation."""
        order = self._create_order()
        order.action_confirm_rental()
        self.assertEqual(order.rental_daily_rate, 500)
        self.pricing.daily_rate = 600
        # Changing the rule must not alter the confirmed order's rate snapshot.
        self.assertEqual(order.rental_daily_rate, 500)

    def test_06_pickup_requires_inspection(self):
        """AT-011: Missing pickup inspection blocks handover."""
        order = self._create_order()
        order.action_confirm_rental()
        with self.assertRaises(UserError):
            order.action_pickup()
        inspection = self.env['car.rental.inspection'].create({
            'inspection_type': 'pickup',
            'rental_order_id': order.id,
            'vehicle_id': self.vehicle.id,
            'mileage': 10000,
            'fuel_level': 'full',
        })
        inspection.action_done()
        order.action_pickup()
        self.assertEqual(order.rental_state, 'active')
        self.assertEqual(self.vehicle.rental_status, 'rented')

    def test_07_pickup_requires_deposit_for_staff(self):
        """Required deposit unpaid - staff are blocked."""
        order = self._create_order()
        order.action_confirm_rental()
        inspection = self.env['car.rental.inspection'].create({
            'inspection_type': 'pickup',
            'rental_order_id': order.id,
            'vehicle_id': self.vehicle.id,
            'mileage': 10000,
        })
        inspection.action_done()
        staff_env_order = order.with_user(self.staff_user)
        with self.assertRaises(UserError):
            staff_env_order.action_pickup()

    def test_07b_deposit_override_by_manager(self):
        """Required deposit unpaid - a Rental Manager may override the block."""
        order = self._create_order()
        order.action_confirm_rental()
        inspection = self.env['car.rental.inspection'].create({
            'inspection_type': 'pickup',
            'rental_order_id': order.id,
            'vehicle_id': self.vehicle.id,
            'mileage': 10000,
        })
        inspection.action_done()
        manager_env_order = order.with_user(self.manager_user)
        manager_env_order.action_pickup()
        self.assertEqual(order.rental_state, 'active')

    def test_08_return_sets_inspection_pending_and_late_charge(self):
        """AT-016: Late return - charge calculated."""
        order = self._create_order(pickup_offset=-6, return_offset=-3)
        order.action_confirm_rental()
        pickup = self.env['car.rental.inspection'].create({
            'inspection_type': 'pickup',
            'rental_order_id': order.id,
            'vehicle_id': self.vehicle.id,
            'mileage': 10000,
        })
        pickup.action_done()
        order.action_pickup()
        late = fields.Datetime.now() - timedelta(days=2, hours=5)
        order.action_return()
        order.actual_return_datetime = late
        order._apply_late_return_charges(late)
        self.assertEqual(order.rental_state, 'returned')
        self.assertEqual(self.vehicle.rental_status, 'inspection_pending')
        late_charges = order.charge_ids.filtered(lambda charge: charge.charge_type == 'late_return')
        self.assertTrue(late_charges)
        self.assertGreater(late_charges.amount, 0)

    def test_09_settle_requires_return_inspection(self):
        """AT-012/013: Clean return - settlement flow; missing return inspection blocks."""
        order = self._create_order()
        order.action_confirm_rental()
        pickup = self.env['car.rental.inspection'].create({
            'inspection_type': 'pickup',
            'rental_order_id': order.id,
            'vehicle_id': self.vehicle.id,
            'mileage': 10000,
        })
        pickup.action_done()
        order.action_pickup()
        order.action_return()
        with self.assertRaises(UserError):
            order.action_settle()
        return_inspection = self.env['car.rental.inspection'].create({
            'inspection_type': 'return',
            'rental_order_id': order.id,
            'vehicle_id': self.vehicle.id,
            'mileage': 10400,
            'fuel_level': 'full',
        })
        return_inspection.action_done()
        order.action_settle()
        self.assertEqual(order.rental_state, 'settled')
        self.assertEqual(self.vehicle.rental_status, 'cleaning')
        order.action_close()
        self.assertEqual(order.rental_state, 'closed')
        self.assertEqual(self.vehicle.rental_status, 'available')

    def test_10_damage_requires_approval_before_settle(self):
        """AT-013: Damaged return - assessment required before settlement."""
        order = self._create_order()
        order.action_confirm_rental()
        pickup = self.env['car.rental.inspection'].create({
            'inspection_type': 'pickup',
            'rental_order_id': order.id,
            'vehicle_id': self.vehicle.id,
            'mileage': 10000,
        })
        pickup.action_done()
        order.action_pickup()
        order.action_return()
        return_inspection = self.env['car.rental.inspection'].create({
            'inspection_type': 'return',
            'rental_order_id': order.id,
            'vehicle_id': self.vehicle.id,
            'mileage': 10400,
        })
        return_inspection.line_ids.filtered(lambda line: line.area == 'exterior')[:1].write({'result': 'damage'})
        return_inspection.action_done()
        self.assertTrue(order.damage_detected)
        self.assertTrue(order.damage_ids)
        with self.assertRaises(UserError):
            order.action_settle()
        damage = order.damage_ids[:1]
        manager_damage = damage.with_user(self.manager_user)
        damage.customer_charge = 300
        manager_damage.action_approve()
        order.action_settle()
        self.assertEqual(order.rental_state, 'settled')
        self.assertEqual(self.vehicle.rental_status, 'damaged')

    def test_11_damage_below_deposit_correct_refund(self):
        """AT-014: Damage below deposit - correct deduction."""
        order = self._create_order()
        order.action_confirm_rental()
        deposit = order.deposit_ids[:1]
        deposit.action_mark_collected()
        self.assertEqual(deposit.status, 'collected')
        damage = self.env['car.rental.damage'].create({
            'rental_order_id': order.id,
            'damage_type': 'scratch',
            'severity': 'minor',
            'customer_charge': 200,
        })
        manager_damage = damage.with_user(self.manager_user)
        manager_damage.action_approve()
        manager_damage.action_apply_deposit()
        self.assertEqual(damage.deposit_applied, 200)
        self.assertEqual(deposit.applied_amount, 200)
        self.assertEqual(deposit.status, 'partially_applied')

    def test_12_damage_above_deposit_balance_invoice(self):
        """AT-015: Damage above deposit - balance invoice linked."""
        order = self._create_order()
        order.action_confirm_rental()
        deposit = order.deposit_ids[:1]
        deposit.action_mark_collected()
        damage = self.env['car.rental.damage'].create({
            'rental_order_id': order.id,
            'damage_type': 'dent',
            'severity': 'major',
            'customer_charge': 1200,
        })
        manager_damage = damage.with_user(self.manager_user)
        manager_damage.action_approve()
        manager_damage.action_apply_deposit()
        manager_damage.action_create_balance_invoice()
        self.assertEqual(damage.deposit_applied, 500)
        self.assertTrue(damage.additional_invoice_id)
        self.assertEqual(damage.additional_invoice_id.amount_total, 700)

    def test_13_pricing_override_requires_manager(self):
        """AT-019: Price override - approval enforced at confirmation."""
        order = self._create_order()
        order.rental_state = 'quotation'
        staff_env_order = order.with_user(self.staff_user)
        # Staff may draft an override, but confirmation is blocked for non-managers.
        staff_env_order.pricing_override = True
        staff_env_order.pricing_override_reason = 'Manager pre-approved discount'
        with self.assertRaises(AccessError):
            staff_env_order.action_confirm_rental()

    def test_14_cross_border_requires_approval(self):
        """Cross-border without approval - block confirmation."""
        self.destination.is_cross_border = True
        self.destination.approval_required = True
        order = self._create_order()
        with self.assertRaises(UserError):
            order.action_confirm_rental()
        order.cross_border_approved = True
        order.action_confirm_rental()
        self.assertEqual(order.rental_state, 'confirmed')

    def test_15_compliance_expiry_blocks_handover(self):
        """Expired compliance blocks handover when the block policy is on."""
        self.company.rental_compliance_block = True
        order = self._create_order()
        order.action_confirm_rental()
        self.vehicle.insurance_expiry = fields.Date.add(self.today, days=-10)
        with self.assertRaises(UserError):
            order.action_pickup()
        self.company.rental_compliance_block = False

    def test_16_maintenance_threshold_cron(self):
        """AT-018: Maintenance threshold - request created."""
        self.vehicle.current_mileage = 90000
        self.vehicle.next_service_mileage = 85000
        self.env['fleet.vehicle']._cron_rental_maintenance()
        request = self.env['maintenance.request'].search([
            ('rental_vehicle_id', '=', self.vehicle.id)])
        self.assertTrue(request)

    def test_17_compliance_cron_activity(self):
        """AT-017: Compliance expiry - activity created."""
        self.vehicle.insurance_expiry = fields.Date.add(self.today, days=30)
        self.env['fleet.vehicle']._cron_rental_compliance()
        activities = self.env['mail.activity'].search([
            ('res_model', '=', 'fleet.vehicle'),
            ('res_id', '=', self.vehicle.id),
        ])
        self.assertTrue(activities)

    def test_18_pricing_write_blocked_after_confirm(self):
        """Historical pricing records must not be freely editable."""
        order = self._create_order()
        order.action_confirm_rental()
        staff_env_order = order.with_user(self.staff_user)
        with self.assertRaises(AccessError):
            staff_env_order.write({'rental_daily_rate': 999})
