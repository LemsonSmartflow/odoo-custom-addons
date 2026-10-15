from datetime import timedelta
import base64
import io

from PIL import Image

from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestConnectedWorkflow(TransactionCase):
    def setUp(self):
        super().setUp()
        company = self.env.company
        accounts = {}
        for index, (name, kind) in enumerate([('Receivable', 'asset_receivable'), ('Rental Income', 'income'), ('Deposits', 'liability_current'), ('Bank', 'asset_cash'), ('Damage Income', 'income'), ('Maintenance Expense', 'expense')]):
            accounts[name] = self.env['account.account'].create({'name': 'Test ' + name, 'code': 'TCR%03d' % index, 'account_type': kind, 'reconcile': kind == 'asset_receivable', 'company_ids': [fields.Command.set(company.ids)]})
        bank = self.env['account.journal'].create({'name': 'Test Rental Bank', 'code': 'TCRB', 'type': 'bank', 'company_id': company.id, 'default_account_id': accounts['Bank'].id})
        sales = self.env['account.journal'].create({'name': 'Test Rental Sales', 'code': 'TCRS', 'type': 'sale', 'company_id': company.id, 'default_account_id': accounts['Rental Income'].id})
        company.write({'cr_income_account_id': accounts['Rental Income'].id, 'cr_damage_account_id': accounts['Damage Income'].id, 'cr_deposit_account_id': accounts['Deposits'].id, 'cr_expense_account_id': accounts['Maintenance Expense'].id, 'cr_cash_journal_id': bank.id, 'cr_sales_journal_id': sales.id, 'cr_rental_product_id': self.env.ref('car_rental_management_odoo.rental_service_product').id, 'cr_tax_id': False, 'rental_block_expired_documents': False, 'rental_require_full_payment': False, 'rental_agreement_terms': 'Test agreement terms'})
        self.accounts = accounts
        self.category = self.env['car.rental.category'].create({'name': 'Test Category'})
        self.destination = self.env['car.rental.zone'].create({'name': 'Test Destination'})
        self.rule = self.env['car.rental.rate.rule'].create({'name': 'Test Rate', 'category_id': self.category.id, 'destination_id': self.destination.id, 'daily_rate': 100})
        self.rule.action_approve()
        image = io.BytesIO()
        Image.new('RGB', (8, 8), 'blue').save(image, format='PNG')
        self.photo = base64.b64encode(image.getvalue())
        self.customer = self.env['car.rental.customer'].create({
            'first_name': 'Workflow', 'last_name': 'Test', 'cin': 'TEST-ID',
            'driving_license': 'TEST-LICENCE',
            'license_expiry': fields.Date.today() + timedelta(days=365),
            'license_issue_date': fields.Date.today() - timedelta(days=365),
            'date_of_birth': fields.Date.today().replace(year=fields.Date.today().year - 30),
            'physical_address': 'Test street', 'postal_address': 'Test PO box',
        })
        identity = self.env['ir.attachment'].create({'name': 'Test identity.png', 'datas': self.photo, 'res_model': 'car.rental.customer', 'res_id': self.customer.id})
        self.customer.write({'omang_document_ids': [fields.Command.set(identity.ids)], 'license_document_ids': [fields.Command.set(identity.ids)]})
        self.vehicle = self.env['car.rental.vehicle'].create({
            'registration_number': 'WORKFLOW-TEST', 'brand': 'Test', 'model': 'Car',
            'daily_price': 100, 'mileage': 1000, 'category_id': self.category.id,
        })
        today = fields.Date.today()
        self.reservation = self.env['car.rental.reservation'].create({
            'customer_id': self.customer.id, 'vehicle_id': self.vehicle.id,
            'start_date': today, 'end_date': today + timedelta(days=3), 'destination_id': self.destination.id,
        })
        self.customer._ensure_partner().property_account_receivable_id = accounts['Receivable']

    def rental(self):
        self.reservation.action_confirm()
        action = self.reservation.action_create_rental()
        return self.env['car.rental.rental'].browse(action['res_id'])

    def payment(self, rental, amount):
        rental.action_invoice()
        invoice = rental.invoice_ids.filtered(lambda i: i.rental_invoice_kind == 'rental')[:1]
        if invoice.state == 'draft':
            invoice.action_post()
        payment = self.env['car.rental.payment'].create({
            'rental_id': rental.id, 'paid_amount': amount, 'payment_method': 'cash',
        })
        payment.action_post_receipt()
        return payment

    def inspection(self, rental, kind, mileage, **extra):
        attachment = self.env['ir.attachment'].create({'name': 'Test vehicle photo.png', 'datas': self.photo, 'res_model': 'car.rental.rental', 'res_id': rental.id})
        vals = {'rental_id': rental.id, 'kind': kind, 'mileage': mileage, 'fuel_level': 'full', 'exterior': 'Good', 'interior': 'Good', 'tyres': 'Good', 'accessories': 'Spare tyre and tools', 'signature': self.photo, 'acknowledged_by': 'Workflow Test', 'photo_ids': [fields.Command.set(attachment.ids)]}
        vals.update(extra)
        check = self.env['car.rental.check'].create(vals)
        check.action_complete()
        return check

    def handover(self, rental):
        if rental.deposit_held < rental.deposit_required:
            self.deposit(rental, 'collect', rental.deposit_required - rental.deposit_held)
        rental.write({'agreement_signature': self.photo, 'agreement_signed_by': 'Workflow Test'})
        rental.action_sign_agreement()
        self.inspection(rental, 'pickup', 1000)
        rental.action_start_rental()

    def test_empty_rental_form_balances_before_reservation(self):
        rental = self.env['car.rental.rental'].new({})
        self.assertFalse(rental.currency_id)
        self.assertEqual(rental.balance_due, 0)
        self.assertEqual(rental.payment_status, 'paid')
        rental.reservation_id = self.reservation
        self.assertEqual(rental.currency_id, self.env.company.currency_id)
        self.assertEqual(rental.balance_due, 300)
        self.assertEqual(rental.payment_status, 'unpaid')

    def test_pricing_deposit_amount_and_daily_rate_onchange(self):
        rule = self.env['car.rental.rate.rule'].new({'daily_rate': 350})
        rule._onchange_daily_rate_deposit()
        self.assertEqual(rule.deposit_amount, 350)
        rule.deposit_amount = 175
        rule._onchange_deposit_amount()
        self.assertEqual(rule.deposit_ratio, 0.5)
        rule.daily_rate = 400
        rule._onchange_daily_rate_deposit()
        self.assertEqual(rule.deposit_amount, 400)
        rule.deposit_amount = 100
        with self.assertRaisesRegex(ValidationError, '50% to 100%'):
            rule._onchange_deposit_amount()
        self.rule.action_draft()
        with self.assertRaisesRegex(ValidationError, '50% to 100%'), self.cr.savepoint():
            self.rule.write({'deposit_amount': 49})
        self.rule.write({'deposit_amount': 50})
        self.assertEqual(self.rule.deposit_ratio, 0.5)
        self.rule.write({'daily_rate': 350})
        self.assertEqual(self.rule.deposit_amount, 350)

    def test_deposit_minimum_and_default_daily_rate(self):
        self.assertEqual(self.rule.deposit_ratio, 1)
        self.assertEqual(self.reservation.deposit_required, 100)
        self.rule.action_draft()
        for ratio in [0, 0.49, 1.01]:
            with self.assertRaisesRegex(ValidationError, '50% and 100%'), self.cr.savepoint():
                self.rule.write({'deposit_ratio': ratio})
        self.rule.write({'deposit_ratio': 0.5})
        self.rule.action_approve()
        self.reservation.action_reprice()
        self.assertEqual(self.reservation.deposit_required, 50)

    def test_invoice_payment_updates_rental_without_custom_receipt(self):
        rental = self.rental()
        rental.action_invoice()
        invoice = rental.invoice_ids
        invoice.action_post()
        move = self.env['account.move'].create({
            'move_type': 'entry', 'journal_id': self.env.company.cr_cash_journal_id.id,
            'line_ids': [
                fields.Command.create({'account_id': self.accounts['Bank'].id, 'debit': 300}),
                fields.Command.create({'account_id': self.accounts['Receivable'].id,
                                      'partner_id': invoice.partner_id.id, 'credit': 300}),
            ],
        })
        move.action_post()
        (invoice.line_ids + move.line_ids).filtered(
            lambda l: l.account_id == self.accounts['Receivable']).reconcile()
        self.assertFalse(rental.payment_ids)
        self.assertEqual(rental.paid_total, 300)
        self.assertEqual(rental.balance_due, 0)
        self.assertEqual(rental.payment_status, 'paid')

    def test_vehicle_details_and_activation_saved_together(self):
        vehicle = self.env['car.rental.vehicle'].create({
            'brand': 'Test', 'model': 'Setup', 'status': 'setup',
        })
        vehicle.write({
            'registration_number': 'ACTIVATE-TEST',
            'category_id': self.category.id,
            'status': 'available',
        })
        self.assertEqual(vehicle.status, 'available')
        self.assertEqual(vehicle.registration_number, 'ACTIVATE-TEST')
        self.assertEqual(vehicle.category_id, self.category)
        self.assertEqual(vehicle.daily_price, 0)

    def test_vehicle_activation_requires_final_saved_details(self):
        vehicle = self.env['car.rental.vehicle'].create({
            'brand': 'Test', 'model': 'Setup', 'status': 'setup',
        })
        with self.assertRaisesRegex(ValidationError, 'Registration Number'), self.cr.savepoint():
            vehicle.write({'status': 'available', 'category_id': self.category.id})
        with self.assertRaisesRegex(ValidationError, 'Category'), self.cr.savepoint():
            vehicle.write({'status': 'available', 'registration_number': 'ACTIVATE-TEST'})
        vehicle.write({'registration_number': 'ACTIVATE-TEST', 'category_id': self.category.id})
        vehicle.action_activate()
        self.assertEqual(vehicle.status, 'available')
        with self.assertRaisesRegex(ValidationError, 'Registration Number'), self.cr.savepoint():
            vehicle.write({'status': 'available', 'registration_number': False})

    def test_vehicle_details_do_not_bypass_release_checks(self):
        self.vehicle._operational_update({'status': 'inspection'})
        with self.assertRaisesRegex(ValidationError, 'inspection, repairs and cleaning'), self.cr.savepoint():
            self.vehicle.write({'registration_number': 'RELEASE-TEST', 'status': 'available'})

    def test_reservation_creates_one_linked_rental(self):
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.reservation.action_create_rental()
        rental = self.rental()
        self.assertEqual(self.reservation.action_create_rental()['res_id'], rental.id)
        self.assertEqual(rental.initial_mileage, 1000)
        self.assertEqual(rental.amount, 300)
        self.assertTrue(self.reservation.reference.startswith('RES '))
        self.assertTrue(rental.reference.startswith('REN '))
        self.assertEqual(self.customer.rental_count, 1)
        self.assertEqual(self.vehicle.rental_count, 1)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['car.rental.rental'].create({'reservation_id': self.reservation.id})

    def test_instalments_share_balance_and_status(self):
        rental = self.rental()
        first = self.payment(rental, 100)
        self.assertEqual(rental.paid_total, 100)
        self.assertEqual(rental.balance_due, 200)
        self.assertEqual(first.remaining_amount, 200)
        self.assertEqual(first.status, 'partial')
        action = rental.action_record_payment()
        self.assertEqual(action['context']['default_rental_id'], rental.id)
        self.assertEqual(action['res_model'], 'car.rental.collection')
        second = self.payment(rental, 200)
        self.assertEqual(rental.payment_status, 'paid')
        self.assertEqual(rental.balance_due, 0)
        self.assertEqual(first.remaining_amount, 0)
        self.assertEqual(first.status, 'paid')
        self.assertTrue(second.reference.startswith('PAY/'))
        # The unified form remains available until the security deposit is collected too.
        self.assertEqual(rental.action_record_payment()['res_model'], 'car.rental.collection')
        with self.assertRaises(ValidationError), self.cr.savepoint():
            second.unlink()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            first.paid_amount = 50

    def test_combined_overpayment_is_rejected(self):
        rental = self.rental()
        first = self.payment(rental, 200)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.payment(rental, 150)
        self.assertEqual(rental.balance_due, 100)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            first.paid_amount = 301
        for amount in (0, -1):
            with self.assertRaises(ValidationError), self.cr.savepoint():
                self.payment(rental, amount)

    def test_pickup_return_updates_vehicle(self):
        rental = self.rental()
        self.payment(rental, 100)
        self.handover(rental)
        self.assertEqual(self.vehicle.status, 'rented')
        with self.assertRaises(ValidationError), self.cr.savepoint():
            rental.action_start_rental()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            rental.action_return_vehicle()
        self.inspection(rental, 'return', 1200)
        rental.action_return_vehicle()
        self.assertEqual(self.vehicle.status, 'inspection')
        self.vehicle.action_mark_cleaning()
        self.vehicle.action_release()
        self.assertEqual(self.vehicle.status, 'available')
        self.assertEqual(self.vehicle.mileage, 1200)
        self.assertEqual(rental.balance_due, 200)
        self.payment(rental, 200)
        self.assertEqual(rental.payment_status, 'paid')

    def test_linked_reservation_is_protected(self):
        self.rental()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.reservation.action_cancel()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.reservation.end_date += timedelta(days=1)

    def test_navigation_and_views(self):
        rental = self.rental()
        payment = self.payment(rental, 100)
        self.assertEqual(payment.action_rental()['res_id'], rental.id)
        self.assertEqual(rental.action_reservation()['res_id'], self.reservation.id)
        self.assertEqual(self.vehicle.action_book()['context']['default_vehicle_id'], self.vehicle.id)
        self.assertEqual(self.customer.action_book()['context']['default_customer_id'], self.customer.id)
        for model, types in {
            'car.rental.vehicle': ['kanban', 'form', 'list'],
            'car.rental.reservation': ['form', 'list'],
            'car.rental.rental': ['form', 'list', 'search'],
            'car.rental.payment': ['form'],
            'car.rental.customer': ['form'],
            'car.rental.dashboard': ['form'],
        }.items():
            for view_type in types:
                self.assertTrue(self.env[model].get_view(view_type=view_type)['arch'])

    def test_duration_rate_and_deposit_snapshot(self):
        self.rule.action_draft()
        self.rule.write({'daily_rate': 500, 'min_days': 4, 'max_days': 7, 'deposit_ratio': 1})
        self.rule.action_approve()
        self.reservation.end_date = self.reservation.start_date + timedelta(days=5)
        self.assertEqual(self.reservation.amount, 2500)
        self.assertEqual(self.reservation.deposit_required, 500)
        self.reservation.action_confirm()
        self.rule.action_draft()
        self.rule.daily_rate = 600
        self.rule.action_approve()
        self.assertEqual(self.reservation.quoted_daily_rate, 500)
        self.assertEqual(self.reservation.amount, 2500)

    def test_missing_and_overlapping_rates(self):
        self.rule.action_draft()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.reservation.action_confirm()
        self.rule.action_approve()
        duplicate = self.env['car.rental.rate.rule'].create({'name': 'Overlapping Rate', 'category_id': self.category.id, 'destination_id': self.destination.id, 'daily_rate': 200})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            duplicate.action_approve()

    def test_staff_cannot_approve_or_bypass_workflow(self):
        staff = self.env['res.users'].with_context(no_reset_password=True).create({'name': 'Test Rental Staff', 'login': 'test-rental-staff', 'company_id': self.env.company.id, 'company_ids': [fields.Command.set(self.env.company.ids)], 'group_ids': [fields.Command.set([self.env.ref('base.group_user').id, self.env.ref('car_rental_management_odoo.group_car_rental_agent').id])]})
        self.reservation.write({'proposed_rate': 80, 'override_reason': 'Corporate customer'})
        self.reservation.with_user(staff).action_request_override()
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.reservation.with_user(staff).action_approve_override()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.reservation.with_user(staff).write({'status': 'confirmed'})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.reservation.with_user(staff).write({'quoted_daily_rate': 1})
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.vehicle.with_user(staff).write({'registration_number': 'CHANGED'})
        self.reservation.action_approve_override()
        self.reservation.action_confirm()
        self.assertEqual(self.reservation.amount, 240)
        self.assertEqual(self.reservation.override_approved_by, self.env.user)

    def test_half_open_availability_and_allocation(self):
        self.reservation.action_confirm()
        start = self.reservation.end_date
        back_to_back = self.env['car.rental.reservation'].create({'customer_id': self.customer.id, 'category_id': self.category.id, 'destination_id': self.destination.id, 'start_date': start, 'end_date': start + timedelta(days=2)})
        back_to_back.action_allocate()
        self.assertEqual(back_to_back.vehicle_id, self.vehicle)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['car.rental.reservation'].create({'customer_id': self.customer.id, 'vehicle_id': self.vehicle.id, 'destination_id': self.destination.id, 'start_date': start - timedelta(days=1), 'end_date': start + timedelta(days=1)})

    def deposit(self, rental, kind, amount, damage=False):
        event = self.env['car.rental.deposit.transaction'].create({'rental_id': rental.id, 'kind': kind, 'amount': amount, 'damage_id': damage.id if damage else False})
        event.action_post()
        return event

    def rental_with_deposit(self):
        self.rule.action_draft()
        self.rule.write({'daily_rate': 500, 'deposit_ratio': 1})
        self.rule.action_approve()
        self.reservation.action_reprice()
        rental = self.rental()
        self.deposit(rental, 'collect', 500)
        self.handover(rental)
        return rental

    def test_deposit_liability_and_full_refund(self):
        rental = self.rental_with_deposit()
        self.assertEqual(rental.deposit_held, 500)
        collection = rental.deposit_transaction_ids[:1]
        liability_lines = collection.account_move_id.line_ids.filtered(lambda l: l.account_id == self.accounts['Deposits'])
        self.assertEqual(sum(liability_lines.mapped('credit')), 500)
        self.assertFalse(collection.account_move_id.line_ids.filtered(lambda l: l.account_id == self.accounts['Rental Income']))
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.deposit(rental, 'refund', 500)
        self.inspection(rental, 'return', 1100)
        rental.action_return_vehicle()
        self.deposit(rental, 'refund', 500)
        self.assertEqual(rental.deposit_held, 0)
        self.assertEqual(rental.deposit_refunded, 500)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            collection.amount = 1

    def damage_case(self, rental, cost):
        self.inspection(rental, 'return', 1200, new_damage=True, damage_notes='Test bumper damage')
        rental.action_return_vehicle()
        damage = rental.damage_ids[:1]
        damage.cost = cost
        damage.action_approve()
        damage.action_invoice()
        damage.invoice_id.action_post()
        return damage

    def test_damage_300_retains_300_refunds_200(self):
        rental = self.rental_with_deposit()
        damage = self.damage_case(rental, 300)
        self.deposit(rental, 'retain', 300, damage)
        self.assertEqual(damage.deposit_retained, 300)
        self.assertEqual(damage.invoice_id.amount_residual, 0)
        self.assertEqual(rental.deposit_held, 200)
        self.deposit(rental, 'refund', 200)
        self.assertEqual(rental.deposit_refunded, 200)
        self.assertEqual(rental.deposit_held, 0)

    def test_damage_2000_retains_500_owes_1500(self):
        rental = self.rental_with_deposit()
        damage = self.damage_case(rental, 2000)
        self.deposit(rental, 'retain', 500, damage)
        self.assertEqual(damage.additional_charge, 1500)
        self.assertEqual(damage.invoice_id.amount_residual, 1500)
        self.assertEqual(rental.deposit_held, 0)
        self.assertEqual(self.vehicle.status, 'damaged')

    def test_unsigned_or_incomplete_handover_blocked(self):
        rental = self.rental()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            rental.action_start_rental()
        rental.write({'agreement_signature': self.photo, 'agreement_signed_by': 'Test Customer'})
        rental.action_sign_agreement()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            rental.action_start_rental()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            rental.agreement_terms = 'Changed terms'

    def test_posted_receipt_reconciles_native_invoice(self):
        rental = self.rental()
        payment = self.payment(rental, 100)
        invoice = rental.invoice_ids[:1]
        self.assertEqual(payment.account_move_id.state, 'posted')
        self.assertEqual(invoice.amount_residual, 200)
        self.assertEqual(rental.financial_balance, 200)
        receivable = payment.account_move_id.line_ids.filtered(lambda l: l.account_id.account_type == 'asset_receivable')
        self.assertTrue(receivable.reconciled)

    def test_late_return_charge(self):
        expected = fields.Datetime.now() - timedelta(hours=27)
        self.reservation.write({'start_date': expected.date() - timedelta(days=3), 'end_date': expected.date(), 'expected_return_datetime': expected})
        rental = self.rental()
        self.handover(rental)
        self.inspection(rental, 'return', 1200)
        rental.action_return_vehicle()
        self.assertEqual(rental.late_days, 2)
        self.assertEqual(rental.late_charge, 200)
        rental.action_late_invoice()
        self.assertEqual(rental.invoice_ids.filtered(lambda m: m.rental_invoice_kind == 'late').amount_total, 200)

    def test_compliance_and_setup_vehicle_blocked(self):
        self.env.company.rental_block_expired_documents = True
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.reservation.action_confirm()
        future = fields.Date.today() + timedelta(days=365)
        self.vehicle.write({'insurance_expiry': future, 'road_license_expiry': future, 'fitness_expiry': future})
        self.reservation.action_confirm()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['car.rental.vehicle'].create({'brand': 'Test', 'model': 'Setup', 'status': 'setup'}).action_book()

    def test_agreement_report_and_new_views(self):
        rental = self.rental()
        report = self.env['ir.actions.report']
        html, _ = report._render_qweb_html('car_rental_management_odoo.rental_agreement', rental.ids)
        self.assertIn(b'Vehicle Rental Agreement', html)
        for model in ['car.rental.check', 'car.rental.damage.case', 'car.rental.deposit.transaction', 'car.rental.rate.rule']:
            self.assertTrue(self.env[model].get_view(view_type='form')['arch'])
        self.assertTrue(self.env['maintenance.request'].get_view(view_type='form')['arch'])
        self.assertTrue(self.env['res.config.settings'].get_view(view_type='form')['arch'])

    def test_reminders_and_service_request_are_idempotent(self):
        self.vehicle.write({'next_service_mileage': 1100, 'insurance_expiry': fields.Date.today() + timedelta(days=10)})
        self.env['car.rental.vehicle']._cron_rental_reminders()
        count = len(self.vehicle.activity_ids)
        requests = len(self.vehicle.maintenance_ids)
        self.assertGreater(count, 0)
        self.assertEqual(requests, 1)
        self.env['car.rental.vehicle']._cron_rental_reminders()
        self.assertEqual(len(self.vehicle.activity_ids), count)
        self.assertEqual(len(self.vehicle.maintenance_ids), requests)

    def test_company_rules_and_accountant_role(self):
        other = self.env['res.company'].create({'name': 'Test Other Rental Company'})
        other_category = self.env['car.rental.category'].create({'name': 'Other Category', 'company_id': other.id})
        staff = self.env['res.users'].with_context(no_reset_password=True).create({'name': 'Limited Rental Staff', 'login': 'limited-rental-staff', 'company_id': self.env.company.id, 'company_ids': [fields.Command.set(self.env.company.ids)], 'group_ids': [fields.Command.set([self.env.ref('base.group_user').id, self.env.ref('car_rental_management_odoo.group_car_rental_agent').id])]})
        with self.assertRaises(AccessError), self.cr.savepoint():
            other_category.with_user(staff).read(['name'])
        rental = self.rental()
        draft = self.env['car.rental.payment'].create({'rental_id': rental.id, 'paid_amount': 100, 'payment_method': 'cash'})
        self.assertEqual(rental.balance_due, 300)
        with self.assertRaises(AccessError), self.cr.savepoint():
            draft.with_user(staff).action_post_receipt()

    def test_receipt_reversal_updates_operational_balance(self):
        rental = self.rental()
        receipt = self.payment(rental, 100)
        receipt.account_move_id._reverse_moves(default_values_list=[{'date': fields.Date.today()}], cancel=True)
        self.assertEqual(rental.paid_total, 0)
        self.assertEqual(rental.balance_due, 300)

    def test_sales_and_rental_share_one_invoice(self):
        rental = self.rental()
        rental.action_quotation()
        order = rental.sale_order_id
        order.action_confirm()
        invoices = order._create_invoices()
        self.assertEqual(invoices.car_rental_id, rental)
        self.assertEqual(rental.action_invoice()['res_id'], invoices.id)
        self.assertEqual(len(rental.invoice_ids), 1)
        self.assertEqual(invoices.invoice_line_ids.account_id, self.accounts['Rental Income'])

    def test_module_invoice_updates_sales_and_blocks_price_bypass(self):
        rental = self.rental()
        rental.action_quotation()
        rental.sale_order_id.action_confirm()
        rental.action_invoice()
        self.assertEqual(rental.sale_order_id.order_line.qty_invoiced, 3)
        invoice = rental.invoice_ids[:1]
        with self.assertRaises(ValidationError), self.cr.savepoint():
            invoice.invoice_line_ids.price_unit = 1
            invoice.action_post()

    def test_batch_sales_invoices_remain_separate_per_rental(self):
        first = self.rental()
        first.action_quotation()
        start = self.reservation.end_date
        booking = self.env['car.rental.reservation'].create({'customer_id': self.customer.id, 'vehicle_id': self.vehicle.id, 'destination_id': self.destination.id, 'start_date': start, 'end_date': start + timedelta(days=2)})
        booking.action_confirm()
        second = self.env['car.rental.rental'].browse(booking.action_create_rental()['res_id'])
        second.action_quotation()
        orders = first.sale_order_id + second.sale_order_id
        orders.action_confirm()
        invoices = orders._create_invoices()
        self.assertEqual(len(invoices), 2)
        self.assertEqual(invoices.mapped('car_rental_id'), first + second)
