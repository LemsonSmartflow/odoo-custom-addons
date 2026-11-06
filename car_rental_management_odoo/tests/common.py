"""Shared fixtures for the car_rental_management_odoo test suite.

The module extends standard Odoo records (res.partner, fleet.vehicle,
account.move, ...), so fixtures build real standard records on a fully
configured company (the one carrying the Car Rental settings) and drive the
public workflow actions rather than poking protected fields directly.
"""
import base64
import io
import uuid
from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged
from odoo.tests.common import new_test_user


def _png(width, height, draw=None):
    from PIL import Image, ImageDraw

    image = Image.new('RGB', (width, height), 'white')
    if draw:
        draw(ImageDraw.Draw(image))
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    return base64.b64encode(buffer.getvalue())


# A small opaque PNG for Image fields (agreement / inspection signatures).
PNG_IMAGE = _png(20, 20)


def _signature():
    return _png(200, 80, lambda draw: draw.line(
        [(20, 40), (60, 12), (100, 62), (140, 18), (180, 48)], fill='black', width=3))


PNG_SIGNATURE = _signature()


@tagged('post_install', '-at_install')
class RentalTestCommon(TransactionCase):
    """Roles, accounting configuration and rental record builders."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.env = cls.env(context=dict(
            cls.env.context, allowed_company_ids=[cls.company.id], tracking_disable=True))
        cls.company.write({
            'rental_require_full_payment': False,
            'rental_block_expired_documents': False,
            'rental_block_tracker': False,
            'rental_allow_direct_invoice': True,
            'rental_late_grace_hours': 2.0,
            'rental_agreement_terms': 'Standard rental agreement terms for tests.',
        })
        cls._ensure_journal_accounts()
        cls.receivable_account = cls._find_account('asset_receivable')
        cls._create_roles()
        cls._counter = 0

    def setUp(self):
        super().setUp()
        self.env = self.env(context=dict(
            self.env.context, allowed_company_ids=[self.company.id], tracking_disable=True))

    # ── configuration helpers ────────────────────────────────────────────────
    @classmethod
    def _find_account(cls, account_type):
        return cls.env['account.account'].search([
            ('account_type', '=', account_type),
            ('company_ids', 'in', cls.company.id),
        ], limit=1)

    @classmethod
    def _ensure_journal_accounts(cls):
        # Self-contained fixtures: a fresh Odoo.sh database has no rental accounts.
        accounts = {}
        for index, (label, kind) in enumerate([
            ('Receivable', 'asset_receivable'), ('Payable', 'liability_payable'),
            ('Rental income', 'income'), ('Deposits', 'liability_current'),
            ('Unpaid deposits', 'liability_current'),
            ('Bank', 'asset_cash'), ('Maintenance', 'expense')]):
            account = cls.env['account.account'].create({
                'name': 'Rental test ' + label, 'code': 'CRT%03d' % index,
                'account_type': kind, 'company_ids': [(6, 0, cls.company.ids)],
                'reconcile': kind in ('asset_receivable', 'liability_payable'),
            })
            accounts['pending_liability' if label == 'Unpaid deposits' else kind] = account
        bank = cls.env['account.journal'].create({
            'name': 'Rental test bank', 'code': 'CRTB', 'type': 'bank',
            'company_id': cls.company.id, 'default_account_id': accounts['asset_cash'].id})
        bank.inbound_payment_method_line_ids.payment_account_id = accounts['asset_cash']
        sales = cls.env['account.journal'].create({
            'name': 'Rental test sales', 'code': 'CRTS', 'type': 'sale',
            'company_id': cls.company.id, 'default_account_id': accounts['income'].id})
        deposit_product = cls.env['product.product'].create({
            'name': 'Rental test security deposit',
            'type': 'service',
            'company_id': cls.company.id,
            'taxes_id': [(5, 0, 0)],
        })
        cls.company.write({
            'cr_cash_journal_id': bank.id, 'cr_sales_journal_id': sales.id,
            'cr_income_account_id': accounts['income'].id,
            'cr_damage_account_id': accounts['income'].id,
            'cr_deposit_account_id': accounts['liability_current'].id,
            'cr_deposit_pending_account_id': accounts['pending_liability'].id,
            'cr_expense_account_id': accounts['expense'].id,
            'cr_rental_product_id': cls.env.ref('car_rental_management_odoo.rental_service_product').id,
            'cr_deposit_product_id': deposit_product.id,
            'cr_delivery_product_id': cls.env.ref('car_rental_management_odoo.rental_delivery_product').id,
            'cr_collection_product_id': cls.env.ref('car_rental_management_odoo.rental_collection_product').id,
            'cr_cleaning_product_id': cls.env.ref('car_rental_management_odoo.rental_cleaning_product').id,
            'cr_late_product_id': cls.env.ref('car_rental_management_odoo.rental_late_product').id,
            'cr_tax_id': False,
        })

    @classmethod
    def _create_roles(cls):
        common = {'company_ids': [(6, 0, [cls.company.id])], 'company_id': cls.company.id}
        cls.user_agent = new_test_user(
            cls.env, login='cr_agent', groups='car_rental_management_odoo.group_car_rental_agent', **common)
        cls.user_manager = new_test_user(
            cls.env, login='cr_manager', groups='car_rental_management_odoo.group_rental_manager', **common)
        cls.user_fleet = new_test_user(
            cls.env, login='cr_fleet', groups='car_rental_management_odoo.group_fleet_manager', **common)
        cls.user_accountant = new_test_user(
            cls.env, login='cr_accountant', groups='car_rental_management_odoo.group_rental_accountant', **common)
        cls.user_plain = new_test_user(cls.env, login='cr_plain', groups='base.group_user', **common)

    # ── record builders ──────────────────────────────────────────────────────
    def _unique(self, label):
        type(self)._counter += 1
        return '%s %s' % (label, self._counter)

    def _attachment(self, name='document.png'):
        return self.env['ir.attachment'].create({
            'name': name, 'datas': PNG_IMAGE, 'company_id': self.company.id})

    def _make_partner(self, **overrides):
        values = {
            'name': self._unique('Renter'),
            'company_type': 'person',
            'street': '1 Test Street',
            'rental_postal_address': 'PO Box 1',
            'rental_identity_type': 'omang',
            'rental_cin': '%09d' % (100000000 + type(self)._counter),
            'rental_date_of_birth': fields.Date.today() - timedelta(days=365 * 30),
            'rental_driving_license': '%014d' % (10000000000000 + type(self)._counter),
            'rental_license_issue_date': fields.Date.today() - timedelta(days=365 * 3),
            'rental_license_expiry': fields.Date.today() + timedelta(days=365 * 2),
            'phone': '0810000000',
            'email': 'renter@example.com',
            'rental_next_of_kin_name': 'Test Next of Kin',
            'rental_next_of_kin_relationship': 'Sibling',
            'rental_next_of_kin_phone': '0811111111',
            'rental_next_of_kin_email': 'kin@example.com',
            'rental_enabled': True,
            'property_account_receivable_id': self.receivable_account.id,
            'rental_omang_document_ids': [(6, 0, [self._attachment('omang.png').id])],
            'rental_license_document_ids': [(6, 0, [self._attachment('licence.png').id])],
        }
        values.update(overrides)
        return self.env['res.partner'].create(values)

    def _make_category(self):
        return self.env['fleet.vehicle.model.category'].create({'name': self._unique('Category')})

    def _make_vehicle(self, category=None, license_plate=None, odometer=10000.0, status='available', **overrides):
        category = category or self._make_category()
        brand = self.env['fleet.vehicle.model.brand'].create({'name': self._unique('Brand')})
        model = self.env['fleet.vehicle.model'].create({
            'name': self._unique('Model'), 'brand_id': brand.id,
            'vehicle_type': 'car', 'category_id': category.id})
        values = {
            'model_id': model.id,
            'license_plate': license_plate or 'B %s' % uuid.uuid4().hex[:5].upper(),
            'company_id': self.company.id,
            'odometer': odometer,
            'rental_status': status,
        }
        values.update(overrides)
        return self.env['fleet.vehicle'].create(values)

    def _make_zone(self, name=None):
        return self.env['car.rental.zone'].create({
            'name': name or self._unique('Destination'), 'company_id': self.company.id})

    def _make_rate_rule(self, category, zone, daily_rate=100.0, deposit_ratio=1.0,
                        min_days=1, max_days=0, approve=True):
        rule = self.env['car.rental.rate.rule'].create({
            'name': self._unique('Rate'), 'company_id': self.company.id,
            'category_id': category.id, 'destination_id': zone.id,
            'min_days': min_days, 'max_days': max_days,
            'daily_rate': daily_rate,             'deposit_ratio': deposit_ratio,
        })
        if approve:
            rule.action_approve()
        return rule

    def _make_reservation(self, partner=None, vehicle=None, zone=None, days=3,
                          start=None, confirm=True, category=None, **overrides):
        partner = partner or self._make_partner()
        vehicle = vehicle or self._make_vehicle()
        zone = zone or self._make_zone()
        category = category or vehicle.rental_category_id
        legacy_cleaning_fee = overrides.pop('cleaning_fee', 0.0)
        self._make_rate_rule(category, zone, daily_rate=overrides.pop('daily_rate', 100.0),
                             deposit_ratio=overrides.pop('deposit_ratio', 1.0))
        start = start or (fields.Datetime.now() + timedelta(days=1)).replace(
            hour=8, minute=0, second=0, microsecond=0)
        values = {
            'company_id': self.company.id,
            'partner_id': partner.id,
            'destination_id': zone.id,
            'category_id': category.id,
            'vehicle_id': vehicle.id,
            'pickup_datetime': start,
            'expected_return_datetime': start + timedelta(days=days),
        }
        values.update(overrides)
        reservation = self.env['car.rental.reservation'].create(values)
        if legacy_cleaning_fee:
            self.env.cr.execute(
                'UPDATE car_rental_reservation SET cleaning_fee = %s WHERE id = %s',
                [legacy_cleaning_fee, reservation.id])
            reservation.invalidate_recordset(['cleaning_fee'])
        if confirm:
            reservation.action_confirm()
        return reservation

    def _make_rental(self, reservation):
        return self.env['car.rental.rental'].create({'reservation_id': reservation.id})

    # ── workflow helpers ─────────────────────────────────────────────────────
    def _complete_pickup_inspection(self, rental, mileage=None, user=None, **overrides):
        values = {
            'rental_id': rental.id,
            'kind': 'pickup',
            'mileage': mileage if mileage is not None else rental.vehicle_id.odometer,
            'fuel_level': 'full',
            'accessory_ids': [(6, 0, [self.env.ref(
                'car_rental_management_odoo.accessory_spare_wheel').id])],
            'accessories_checked': True,
            'signature': PNG_SIGNATURE,
            'acknowledged_by': rental.partner_id.display_name,
            'clean': True,
            'photo_ids': [(6, 0, [self._attachment('pickup.png').id])],
        }
        values.update(overrides)
        check = self.env['car.rental.check'].create(values)
        (check.with_user(user) if user else check).action_complete()
        return check

    def _complete_return_inspection(self, rental, mileage=None, **overrides):
        values = {
            'rental_id': rental.id,
            'kind': 'return',
            'mileage': mileage if mileage is not None else rental.initial_mileage + 250,
            'fuel_level': 'half',
            'accessory_ids': [(6, 0, [self.env.ref(
                'car_rental_management_odoo.accessory_spare_wheel').id])],
            'accessories_checked': True,
            'signature': PNG_SIGNATURE,
            'acknowledged_by': rental.partner_id.display_name,
            'clean': True,
            'photo_ids': [(6, 0, [self._attachment('return.png').id])],
        }
        values.update(overrides)
        check = self.env['car.rental.check'].create(values)
        check.action_complete()
        return check

    def _sign_agreement(self, rental):
        rental.write({
            'agreement_terms': 'Approved rental terms.',
            'agreement_signature': PNG_SIGNATURE,
            'agreement_signed_by': rental.partner_id.display_name,
        })
        rental.action_sign_agreement()

    def _collect_deposit(self, rental):
        deposit = self.env['car.rental.deposit.transaction'].create({
            'rental_id': rental.id, 'kind': 'collect', 'amount': rental.deposit_required})
        deposit.action_post()
        return deposit

    def _ready_to_handover(self, reservation=None):
        """Return a draft rental with inspection, signed agreement and deposit."""
        reservation = reservation or self._make_reservation()
        rental = self._make_rental(reservation)
        self._complete_pickup_inspection(rental)
        self._sign_agreement(rental)
        self._collect_deposit(rental)
        rental.vehicle_id._refresh_reserved_status()
        return rental
