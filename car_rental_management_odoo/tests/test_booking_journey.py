"""Sequential booking journey and hire/deposit invoice tests."""
import base64
from datetime import timedelta
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged
from odoo.tools import file_open

from ..models.digital_contract import CUSTOMER_FIELDS
from .common import PNG_IMAGE, PNG_SIGNATURE, RentalTestCommon


@tagged('post_install', '-at_install')
class TestBookingJourney(RentalTestCommon):

    def _new_journey(self, *, vehicle=True, partner=None):
        partner = partner or self._make_partner()
        category = self._make_category()
        zone = self._make_zone()
        selected_vehicle = self._make_vehicle(
            category=category, rental_image=PNG_IMAGE) if vehicle else False
        self._make_rate_rule(category, zone)
        start = (fields.Datetime.now() + timedelta(days=2)).replace(
            hour=8, minute=0, second=0, microsecond=0)
        journey = self.env['car.rental.journey'].create({
            'company_id': self.company.id,
            'booking_partner_id': partner.id,
            'booking_destination_id': zone.id,
            'booking_category_id': category.id,
            'booking_vehicle_id': selected_vehicle.id if selected_vehicle else False,
            'booking_pickup_datetime': start,
            'booking_number_of_days': 3,
        })
        return journey

    def _to_agreement(self, journey):
        journey.action_continue()
        self.assertEqual(journey.step, 'quote')
        self.assertTrue(journey.reservation_id)
        journey.action_continue()
        self.assertEqual(journey.step, 'agreement')
        return journey.rental_id

    def _pay_invoice(self, journey, amount=None, user=None):
        rental = journey.rental_id
        invoice = rental.invoice_ids.filtered(
            lambda move: move.rental_invoice_kind == 'rental')[:1]
        self.assertTrue(invoice)
        credit = min(
            max(rental.deposit_required - rental.deposit_held, 0),
            rental._available_deposit_credit())
        values = {
            'rental_id': rental.id,
            'amount': max(invoice.amount_residual - credit, 0) if amount is None else amount,
            'credit_to_apply': credit,
            'payment_method': 'bank_transfer',
            'reference': 'JOURNEY-RECEIPT',
        }
        wizard = self.env['car.rental.collection']
        if user:
            wizard = wizard.with_user(user)
        wizard = wizard.create(values)
        wizard.action_post()
        return wizard

    def _account_balance(self, partner, account):
        lines = self.env['account.move.line'].search([
            ('partner_id', '=', partner.id),
            ('company_id', '=', self.company.id),
            ('account_id', '=', account.id),
            ('move_id.state', '=', 'posted'),
        ])
        return -sum(lines.mapped('balance'))

    def test_sales_confirmation_rejects_modified_booking_quote(self):
        journey = self._new_journey()
        journey.action_continue()
        order = journey.sales_order_id
        hire = order.order_line.filtered(
            lambda line: not line.rental_deposit_line and not line.rental_charge_kind)
        hire.price_unit += 1

        with self.assertRaisesRegex(ValidationError, 'hire line'), self.cr.savepoint():
            order.action_quotation_send()
        with self.assertRaisesRegex(ValidationError, 'hire line'), self.cr.savepoint():
            order.action_confirm()

        self.assertEqual(order.state, 'draft')
        self.assertEqual(journey.step, 'quote')

    def test_sales_quote_cancellation_cancels_the_booking_and_releases_vehicle(self):
        journey = self._new_journey()
        journey.action_continue()
        rental = journey.rental_id
        vehicle = rental.vehicle_id
        order = journey.sales_order_id

        order.action_cancel()

        self.assertEqual(order.state, 'cancel')
        self.assertEqual(journey.step, 'cancelled')
        self.assertEqual(journey.reservation_id.status, 'cancelled')
        self.assertEqual(rental.status, 'cancelled')
        self.assertEqual(vehicle.rental_status, 'available')

    def test_expired_sales_quote_cron_cancels_pending_booking(self):
        journey = self._new_journey()
        journey.action_continue()
        order = journey.sales_order_id
        order.validity_date = fields.Date.today() - timedelta(days=1)

        self.env['sale.order']._cron_cancel_expired_rental_quotes()

        self.assertEqual(order.state, 'cancel')
        self.assertEqual(journey.step, 'cancelled')

    def test_fleet_vehicle_default_is_applied_to_new_booking(self):
        vehicle = self._make_vehicle()
        action = vehicle.action_rental_book()
        journey = self.env['car.rental.journey'].with_context(
            action['context']).create({})

        self.assertEqual(journey.booking_vehicle_id, vehicle)

    def _assert_signing_hook_called_once(self, rental, sign):
        calls = []
        original = type(rental)._on_agreement_signed

        def tracked(records):
            calls.append(records.ids)
            return original(records)

        with patch.object(type(rental), '_on_agreement_signed', tracked):
            sign()
        self.assertEqual(len(calls), 1)

    def test_booking_to_closed_one_hire_and_deposit_invoice(self):
        journey = self._new_journey()
        rental = self._to_agreement(journey)
        self._sign_agreement(rental)
        journey.invalidate_recordset()
        self.assertEqual(journey.step, 'payment')

        invoice = rental.invoice_ids.filtered(
            lambda move: move.rental_invoice_kind == 'rental')
        self.assertEqual(len(invoice), 1)
        deposit_lines = invoice.invoice_line_ids.filtered('rental_deposit_line')
        hire_lines = invoice.invoice_line_ids.filtered(
            lambda line: line.display_type == 'product' and not line.rental_deposit_line)
        self.assertEqual(len(deposit_lines), 1)
        self.assertEqual(deposit_lines.account_id, self.company.cr_deposit_account_id)
        self.assertFalse(deposit_lines.tax_ids)
        self.assertEqual(hire_lines.sale_line_ids, rental.sale_order_id.order_line.filtered(
            lambda line: not line.rental_deposit_line))
        self.assertEqual(invoice.amount_total, rental.amount + rental.deposit_required)
        self.assertEqual(
            self._account_balance(rental.partner_id, self.company.cr_deposit_account_id),
            rental.deposit_held)
        self.assertEqual(
            self._account_balance(
                rental.partner_id, self.company.cr_deposit_pending_account_id),
            rental.deposit_required)

        self._pay_invoice(journey, user=self.user_accountant)
        journey.invalidate_recordset()
        self.assertEqual(journey.step, 'pickup')
        self.assertEqual(rental.deposit_held, rental.deposit_required)
        self.assertEqual(
            self._account_balance(rental.partner_id, self.company.cr_deposit_account_id),
            rental.deposit_held)
        self.assertEqual(
            self._account_balance(
                rental.partner_id, self.company.cr_deposit_pending_account_id), 0)

        pickup = self._complete_pickup_inspection(rental, user=self.user_agent)
        journey.invalidate_recordset()
        self.assertEqual(journey.step, 'pickup')
        self.assertEqual(journey.action_handover()['res_model'], journey._name)
        self.assertEqual(rental.status, 'ongoing')
        self.assertEqual(journey.step, 'on_hire')
        journey.action_continue()
        self.assertEqual(journey.step, 'on_hire')
        journey.action_begin_return()
        self.assertEqual(journey.step, 'return')

        self._complete_return_inspection(rental)
        journey.action_continue()
        self.assertEqual(rental.status, 'returned')
        self.assertEqual(journey.step, 'settlement')
        self.assertTrue(pickup.exists())

        journey.with_user(self.user_accountant).action_continue()
        self.assertEqual(rental.deposit_held, 0)
        self.assertEqual(
            self._account_balance(rental.partner_id, self.company.cr_deposit_account_id),
            rental.deposit_held)
        journey.with_user(self.user_accountant).action_close_rental()
        self.assertEqual(rental.status, 'closed')
        self.assertEqual(journey.step, 'closed')

    def test_back_navigation_can_resume_every_completed_stage(self):
        journey = self._new_journey()
        rental = self._to_agreement(journey)
        self._sign_agreement(rental)
        self.assertEqual(journey.step, 'payment')

        journey.action_back()
        self.assertEqual(journey.step, 'agreement')
        self.assertTrue(journey.agreement_signed)
        journey.action_continue()
        self.assertEqual(journey.step, 'payment')

        self._pay_invoice(journey, user=self.user_accountant)
        self.assertEqual(journey.step, 'pickup')
        journey.action_back()
        self.assertEqual(journey.step, 'payment')
        self.assertTrue(journey.payment_ready)
        journey.action_continue()
        self.assertEqual(journey.step, 'pickup')

        self._complete_pickup_inspection(rental, user=self.user_agent)
        journey.action_handover()
        self.assertEqual(rental.status, 'ongoing')
        self.assertEqual(journey.step, 'on_hire')
        journey.action_back()
        self.assertEqual(journey.step, 'on_hire')
        journey.action_begin_return()
        self.assertEqual(journey.step, 'return')
        journey.action_back()
        self.assertEqual(journey.step, 'on_hire')
        self.assertEqual(journey.rental_status, 'ongoing')
        journey.action_begin_return()
        self.assertEqual(journey.step, 'return')

        self._complete_return_inspection(rental)
        journey.action_continue()
        self.assertEqual(rental.status, 'returned')
        self.assertEqual(journey.step, 'settlement')
        journey.action_back()
        self.assertEqual(journey.step, 'return')
        self.assertEqual(journey.rental_status, 'returned')
        with self.assertRaisesRegex(ValidationError, 'before the vehicle is returned'):
            journey.return_collection_service = True
        journey.action_continue()
        self.assertEqual(journey.step, 'settlement')

    def test_vehicle_choice_opens_photo_picker_and_full_image_action(self):
        journey = self._new_journey(vehicle=False)
        action = journey.with_user(self.user_agent).action_vehicle_preview()
        preview = self.env[action['res_model']].with_user(self.user_agent).browse(action['res_id'])
        self.assertFalse(preview.vehicle_id)
        vehicle = self._make_vehicle(
            category=journey.booking_category_id, rental_image=PNG_IMAGE)
        preview.vehicle_id = vehicle
        self.assertTrue(preview.image)
        full_picture = preview.action_full_picture()
        self.assertEqual(full_picture['target'], 'new')
        self.assertIn('/web/image/fleet.vehicle/%s/' % vehicle.id, full_picture['url'])
        preview.action_select_vehicle()
        self.assertEqual(journey.booking_vehicle_id, vehicle)

    def test_delivery_is_quoted_and_vehicle_collection_is_not_a_booking_charge(self):
        journey = self._new_journey()
        journey.write({
            'booking_delivery_service': True,
            'booking_delivery_address': '12 Test Road',
            'booking_delivery_fee': 25,
        })
        journey.action_continue()
        self.assertEqual(journey.step, 'quote')
        self.assertEqual(journey.reservation_id.delivery_fee, 25)
        self.assertFalse(journey.reservation_id.collection_service)
        journey.action_back()
        self.assertTrue(journey.booking_delivery_service)
        self.assertEqual(journey.booking_delivery_address, '12 Test Road')
        self.assertEqual(journey.booking_delivery_fee, 25)
        journey.action_continue()
        self.assertEqual(journey.step, 'quote')
        journey.action_continue()
        rental = journey.rental_id
        self.assertEqual(journey.step, 'agreement')
        self.assertEqual(rental.sale_order_id.amount_total, rental.amount + 25 + rental.deposit_required)
        order_lines = rental.sale_order_id.order_line.filtered('rental_charge_kind')
        self.assertEqual(set(order_lines.mapped('rental_charge_kind')), {'delivery'})
        self.assertEqual(
            set(order_lines.mapped('product_id').ids),
            {self.company.cr_delivery_product_id.id})
        self._sign_agreement(rental)
        invoice = rental.invoice_ids.filtered(
            lambda move: move.rental_invoice_kind == 'rental')
        service_lines = invoice.invoice_line_ids.filtered(
            lambda line: line.rental_charge_kind in ('delivery', 'collection'))
        self.assertEqual(len(service_lines), 1)
        self.assertEqual(invoice.amount_total, rental.amount + 25 + rental.deposit_required)
        self.assertEqual(
            set(service_lines.mapped('sale_line_ids').ids), set(order_lines.ids))

    def test_booking_quote_uses_native_sales_send_and_confirmation(self):
        journey = self._new_journey().with_user(self.user_agent)
        journey.action_continue()
        self.assertEqual(journey.step, 'quote')
        order = journey.rental_id.sale_order_id
        self.assertTrue(order)
        self.assertEqual(order.state, 'draft')

        open_action = journey.action_open_quotation()
        self.assertEqual(open_action['res_model'], 'sale.order')
        self.assertEqual(open_action['res_id'], order.id)

        send_action = journey.action_send_quotation()
        self.assertEqual(send_action['res_model'], 'mail.compose.message')

        journey.action_confirm_quotation()
        self.assertEqual(order.state, 'sale')
        self.assertEqual(journey.step, 'agreement')

    def test_existing_quote_stage_prepares_missing_sales_order_on_demand(self):
        journey = self._new_journey()
        journey._ensure_draft_reservation()
        journey._advance_to('quote')
        self.assertFalse(journey.reservation_id.rental_ids)

        send_action = journey.action_send_quotation()

        self.assertEqual(send_action['res_model'], 'mail.compose.message')
        self.assertEqual(journey.rental_id.sale_order_id.state, 'draft')
        self.assertEqual(journey.step, 'quote')

    def test_native_sales_confirmation_advances_booking_agreement(self):
        journey = self._new_journey()
        journey.action_continue()
        order = journey.rental_id.sale_order_id
        order.sudo().action_confirm()
        journey.invalidate_recordset(['step'])
        self.assertEqual(journey.step, 'agreement')

    def test_booking_sends_customer_agreement_link_without_opening_contract(self):
        form_arch = self.env['car.rental.journey'].get_view(view_type='form')['arch']
        self.assertIn('name="action_send_agreement"', form_arch)
        self.assertNotIn('name="action_share_agreement_whatsapp"', form_arch)
        self.assertNotIn('name="action_share_agreement_telegram"', form_arch)
        with file_open('car_rental_management_odoo/data/city_delights_contract.pdf', 'rb') as source:
            self.company.write({
                'cr_contract_pdf': base64.b64encode(source.read()),
                'cr_contract_version': 'Test version',
            })
        journey = self._new_journey().with_user(self.user_agent)
        rental = self._to_agreement(journey)
        journey.write({
            'agreement_company_email': 'office@example.test',
            'agreement_company_representative': 'Company Director',
            'agreement_company_witness_1': 'Company Witness One',
            'agreement_company_witness_2': 'Company Witness Two',
            'agreement_renter_witness_1': 'Renter Witness One',
            'agreement_renter_witness_2': 'Renter Witness Two',
        })

        action = journey.action_send_agreement()
        self.assertEqual(action['res_model'], 'car.rental.agreement.send.wizard')
        self.assertEqual(action['target'], 'new')
        wizard = self.env[action['res_model']].with_user(self.user_agent).create({
            'journey_id': journey.id,
            'method': 'email',
        })
        self.env['ir.config_parameter'].sudo().set_param(
            'web.base.url', 'https://rental.example.com')
        wizard.action_send()
        contract = rental.contract_ids.filtered(lambda item: item.state == 'sent')
        self.assertEqual(len(contract), 1)
        self.assertEqual(contract.delivery_place, journey.reservation_id.destination_id.name)
        self.assertEqual(contract.signer_ids.filtered(
            lambda signer: signer.role == 'renter').name, rental.partner_id.display_name)
        customer_mail = self.env['mail.mail'].sudo().search([
            ('email_to', '=', rental.partner_id.email),
            ('subject', '=', 'Rental agreement for %s' % rental.reference),
        ], order='id desc', limit=1)
        self.assertTrue(customer_mail)
        self.assertEqual(customer_mail.state, 'outgoing')
        renter = contract.signer_ids.filtered(lambda signer: signer.role == 'renter')
        self.assertIn(renter.link, customer_mail.body_html)
        self.assertEqual(journey.agreement_contract_state, 'sent')

    def test_agreement_delivery_place_defaults_to_customer_delivery_address(self):
        journey = self._new_journey()
        journey.write({
            'booking_delivery_service': True,
            'booking_delivery_address': '12 Test Road',
            'booking_delivery_fee': 25,
        })

        self._to_agreement(journey)

        self.assertEqual(journey.agreement_delivery_place, '12 Test Road')

    def test_agreement_signing_link_can_be_copied_and_shared(self):
        with file_open('car_rental_management_odoo/data/city_delights_contract.pdf', 'rb') as source:
            self.company.write({
                'cr_contract_pdf': base64.b64encode(source.read()),
                'cr_contract_version': 'Test version',
            })
        journey = self._new_journey()
        self._to_agreement(journey)
        journey.write({'agreement_company_email': 'office@example.test'})

        action = journey.action_send_agreement()
        wizard_model = self.env[action['res_model']]
        self.assertEqual(
            set(dict(wizard_model._fields['method'].selection)),
            {'email', 'whatsapp', 'telegram'})
        local_share = wizard_model.create({
            'journey_id': journey.id,
            'method': 'whatsapp',
        })
        with self.assertRaisesRegex(ValidationError, 'publicly reachable HTTPS'):
            local_share.action_send()
        self.assertFalse(journey.rental_id.contract_ids)

        self.env['ir.config_parameter'].sudo().set_param(
            'web.base.url', 'https://rental.example.com')
        whatsapp = wizard_model.create({
            'journey_id': journey.id,
            'method': 'whatsapp',
        }).action_send()
        signing_url = journey.agreement_signing_url
        self.assertTrue(signing_url)
        self.assertEqual(whatsapp['target'], 'new')
        self.assertEqual(urlparse(whatsapp['url']).netloc, 'wa.me')
        whatsapp_text = parse_qs(urlparse(whatsapp['url']).query)['text'][0]
        self.assertEqual(whatsapp_text.splitlines()[-1], signing_url)
        self.assertTrue(signing_url.startswith('https://rental.example.com/'))

        telegram = wizard_model.create({
            'journey_id': journey.id,
            'method': 'telegram',
        }).action_send()
        telegram_params = parse_qs(urlparse(telegram['url']).query)
        self.assertEqual(urlparse(telegram['url']).netloc, 't.me')
        self.assertEqual(telegram_params['url'], [signing_url])

    def test_vehicle_picker_lists_only_available_cars_and_applies_selection(self):
        journey = self._new_journey(vehicle=False)
        category = journey.booking_category_id
        available = self._make_vehicle(category=category)
        conflicting = self._make_vehicle(category=category)
        other_category = self._make_vehicle(category=self._make_category())

        self.env['car.rental.reservation'].create({
            'company_id': self.company.id,
            'partner_id': journey.booking_partner_id.id,
            'destination_id': journey.booking_destination_id.id,
            'category_id': category.id,
            'vehicle_id': conflicting.id,
            'pickup_datetime': journey.booking_pickup_datetime,
            'expected_return_datetime': journey.booking_return_datetime,
        })

        action = journey.with_user(self.user_agent).action_vehicle_preview()
        preview = self.env[action['res_model']].with_user(self.user_agent).browse(action['res_id'])
        self.assertEqual(action['target'], 'new')
        self.assertEqual(preview.option_ids.mapped('vehicle_id'), available)
        self.assertNotIn(conflicting, preview.option_ids.mapped('vehicle_id'))
        self.assertNotIn(other_category, preview.option_ids.mapped('vehicle_id'))

        option = preview.option_ids.filtered(lambda line: line.vehicle_id == available)
        refresh = option.action_select()
        self.assertEqual(refresh['res_model'], preview._name)
        self.assertEqual(preview.vehicle_id, available)
        option.invalidate_recordset(['selected', 'selected_label'])
        self.assertTrue(option.selected)
        self.assertEqual(option.selected_label, 'Selected')

        preview.action_select_vehicle()
        self.assertEqual(journey.booking_vehicle_id, available)

    def test_vehicle_picker_rejects_a_vehicle_booked_for_the_same_period(self):
        journey = self._new_journey(vehicle=False)
        category = journey.booking_category_id
        conflicting = self._make_vehicle(category=category)
        self.env['car.rental.reservation'].create({
            'company_id': self.company.id,
            'partner_id': journey.booking_partner_id.id,
            'destination_id': journey.booking_destination_id.id,
            'category_id': category.id,
            'vehicle_id': conflicting.id,
            'pickup_datetime': journey.booking_pickup_datetime,
            'expected_return_datetime': journey.booking_return_datetime,
        })
        action = journey.with_user(self.user_agent).action_vehicle_preview()
        preview = self.env[action['res_model']].with_user(self.user_agent).browse(action['res_id'])
        with self.assertRaises(ValidationError):
            preview.write({'vehicle_id': conflicting.id})
            preview.action_select_vehicle()

    def test_single_signature_advances_booking_and_calls_hook_once(self):
        journey = self._new_journey()
        rental = self._to_agreement(journey)
        self._assert_signing_hook_called_once(
            rental, lambda: self._sign_agreement(rental))
        journey.invalidate_recordset()
        self.assertEqual(journey.step, 'payment')
        self.assertEqual(len(rental.invoice_ids.filtered(
            lambda move: move.rental_invoice_kind == 'rental')), 1)

    def test_six_signature_completion_advances_booking_and_calls_hook_once(self):
        journey = self._new_journey()
        rental = self._to_agreement(journey)
        with file_open('car_rental_management_odoo/data/city_delights_contract.pdf', 'rb') as source:
            self.company.write({
                'cr_contract_pdf': base64.b64encode(source.read()),
                'cr_contract_version': 'Test version',
            })
        contract = self.env['car.rental.contract'].browse(
            rental.action_digital_contract()['res_id'])
        contract.write({
            'delivery_place': 'Office',
            'company_email': 'office@example.test',
            'company_representative': 'Director',
            'company_witness_1': 'Company witness one',
            'company_witness_2': 'Company witness two',
            'renter_witness_1': 'Renter witness one',
            'renter_witness_2': 'Renter witness two',
        })
        contract.action_prepare()
        renter = contract.signer_ids.filtered(lambda signer: signer.role == 'renter')
        other_signers = contract.signer_ids - renter
        particulars = dict(
            {key: 'Test value' for key, _label in CUSTOMER_FIELDS},
            email='customer@example.test',
            kin_email='kin@example.test',
        )

        def complete_signatures():
            renter._submit(particulars, PNG_SIGNATURE)
            for signer in other_signers:
                signer._submit({}, PNG_SIGNATURE)

        self._assert_signing_hook_called_once(rental, complete_signatures)
        journey.invalidate_recordset()
        self.assertEqual(contract.state, 'complete')
        self.assertEqual(journey.step, 'payment')
        self.assertEqual(len(rental.invoice_ids.filtered(
            lambda move: move.rental_invoice_kind == 'rental')), 1)

    def test_partial_policy_requires_deposit_before_pickup(self):
        self.company.rental_require_full_payment = False
        journey = self._new_journey()
        rental = self._to_agreement(journey)
        self._sign_agreement(rental)
        deposit = rental.deposit_required
        self._pay_invoice(journey, amount=deposit - 1, user=self.user_accountant)
        journey.invalidate_recordset()
        self.assertEqual(journey.step, 'payment')
        self.assertLess(rental.deposit_held, deposit)
        self.assertIn(
            'Apply eligible deposit credit or pay the full security deposit.',
            rental._journey_payment_blockers())

        self._pay_invoice(journey, amount=1, user=self.user_accountant)
        journey.invalidate_recordset()
        self.assertEqual(journey.step, 'pickup')
        self.assertEqual(rental.deposit_held, deposit)
        self.assertGreater(rental.balance_due, 0)

    def test_agent_can_drive_operational_steps_but_not_accounting_actions(self):
        journey = self._new_journey()
        rental = self._to_agreement(journey)
        self._sign_agreement(rental)
        self.assertEqual(journey.step, 'payment')
        with self.assertRaises(AccessError):
            journey.with_user(self.user_agent).action_collect_payment()
        self._pay_invoice(journey, user=self.user_accountant)
        self._complete_pickup_inspection(rental, user=self.user_agent)
        journey.invalidate_recordset()
        journey.with_user(self.user_agent).action_handover()
        journey.with_user(self.user_agent).action_begin_return()
        self._complete_return_inspection(rental)
        journey.with_user(self.user_agent).action_continue()
        self.assertEqual(journey.step, 'settlement')
        with self.assertRaises(AccessError):
            journey.with_user(self.user_agent).action_continue()
        with self.assertRaises(AccessError):
            journey.with_user(self.user_agent).action_close_rental()

    def test_signed_unpaid_booking_cancellation_credits_invoice(self):
        journey = self._new_journey()
        rental = self._to_agreement(journey)
        self._sign_agreement(rental)
        invoice = rental.invoice_ids.filtered(
            lambda move: move.rental_invoice_kind == 'rental')
        self.assertEqual(invoice.state, 'posted')
        journey.with_user(self.user_accountant).action_cancel()
        self.assertEqual(rental.status, 'cancelled')
        self.assertEqual(journey.step, 'cancelled')
        self.assertEqual(journey.reservation_id.status, 'cancelled')
        self.assertEqual(rental.vehicle_id.rental_status, 'available')
        self.assertTrue(invoice.reversal_move_ids)

    def test_cancelling_booking_releases_vehicle_and_preserves_history(self):
        journey = self._new_journey()
        rental = self._to_agreement(journey)
        reservation = journey.reservation_id
        vehicle = rental.vehicle_id
        journey.with_user(self.user_agent).action_cancel()

        self.assertEqual(reservation.status, 'cancelled')
        self.assertEqual(rental.status, 'cancelled')
        self.assertEqual(vehicle.rental_status, 'available')
        with self.assertRaisesRegex(ValidationError, 'linked rental history'):
            reservation.unlink()

        replacement = self.env['car.rental.reservation'].create({
            'company_id': self.company.id,
            'partner_id': self._make_partner().id,
            'destination_id': reservation.destination_id.id,
            'category_id': reservation.category_id.id,
            'vehicle_id': vehicle.id,
            'pickup_datetime': reservation.pickup_datetime,
            'expected_return_datetime': reservation.expected_return_datetime,
        })
        replacement.action_confirm()
        self.assertEqual(replacement.vehicle_id, vehicle)
        self.assertEqual(replacement.status, 'confirmed')

    def test_paid_booking_cancellation_refunds_and_reverses_liability(self):
        journey = self._new_journey()
        rental = self._to_agreement(journey)
        self._sign_agreement(rental)
        self._pay_invoice(journey, user=self.user_accountant)
        invoice = rental.invoice_ids.filtered(
            lambda move: move.rental_invoice_kind == 'rental')
        journey.with_user(self.user_accountant).action_cancel()
        refunds = rental.payment_ids.filtered(lambda payment: payment.payment_type == 'outbound')
        self.assertEqual(sum(refunds.mapped('amount')), invoice.amount_total)
        self.assertEqual(
            self._account_balance(rental.partner_id, self.company.cr_deposit_account_id), 0)
        self.assertEqual(
            self._account_balance(
                rental.partner_id, self.company.cr_deposit_pending_account_id), 0)

    def test_standard_invoice_payment_advances_journey_and_reclassifies_deposit(self):
        journey = self._new_journey()
        rental = self._to_agreement(journey)
        self._sign_agreement(rental)
        invoice = rental.invoice_ids.filtered(
            lambda move: move.rental_invoice_kind == 'rental')
        payment = self.env['account.payment'].with_user(self.user_accountant).create({
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': rental.partner_id.id,
            'amount': invoice.amount_total,
            'date': fields.Date.today(),
            'journal_id': self.company.cr_cash_journal_id.id,
            'payment_reference': 'STANDARD-INVOICE-PAYMENT',
        })
        payment.action_post()
        receivable = invoice.line_ids.filtered(
            lambda line: line.account_id.account_type == 'asset_receivable')
        payment_lines = payment.move_id.line_ids.filtered(
            lambda line: line.account_id.account_type == 'asset_receivable')
        (receivable + payment_lines).reconcile()
        journey.invalidate_recordset()
        self.assertEqual(journey.step, 'pickup')
        self.assertEqual(rental.deposit_held, rental.deposit_required)
        self.assertEqual(
            self._account_balance(rental.partner_id, self.company.cr_deposit_account_id),
            rental.deposit_held)

    def test_prior_deposit_credit_keeps_liability_held_and_applies_to_invoice(self):
        partner = self._make_partner()
        source = self._make_rental(self._make_reservation(partner=partner))
        self._collect_deposit(source)
        self._complete_pickup_inspection(source)
        self._sign_agreement(source)
        source.action_start_rental()
        self._complete_return_inspection(source)
        source.action_return_vehicle()
        self.assertEqual(source.deposit_held, source.deposit_required)

        journey = self._new_journey(partner=partner)
        target = self._to_agreement(journey)
        self._sign_agreement(target)
        self.assertEqual(
            self._account_balance(partner, self.company.cr_deposit_account_id),
            source.deposit_held + target.deposit_held)
        self._pay_invoice(journey, user=self.user_accountant)
        journey.invalidate_recordset()
        self.assertEqual(source.deposit_held, 0)
        self.assertEqual(target.deposit_held, target.deposit_required)
        self.assertEqual(
            self._account_balance(partner, self.company.cr_deposit_account_id),
            source.deposit_held + target.deposit_held)

    def test_damage_settlement_invoice_and_shortfall_payment(self):
        self.company.rental_require_full_payment = False
        journey = self._new_journey()
        rental = self._to_agreement(journey)
        self._sign_agreement(rental)
        self._pay_invoice(journey, user=self.user_accountant)
        self._complete_pickup_inspection(rental)
        journey.action_handover()
        journey.action_begin_return()
        self._complete_return_inspection(
            rental, new_damage=True, damage_notes='Damaged mirror')
        journey.action_continue()
        damage = rental.damage_ids.filtered(lambda case: case.state == 'draft')
        with self.assertRaises(ValidationError):
            journey.with_user(self.user_accountant).action_continue()
        journey.invalidate_recordset(['guidance'])
        self.assertEqual(journey.guidance, 'Manager approval of damage required before settlement.')
        damage.write({'cost': rental.deposit_required + 50})
        damage.with_user(self.user_manager).action_approve()
        action = journey.with_user(self.user_accountant).action_continue()
        settlement = rental.invoice_ids.filtered(
            lambda move: move.rental_invoice_kind == 'settlement')
        self.assertEqual(len(settlement), 1)
        self.assertEqual(settlement.state, 'posted')
        self.assertEqual(damage.invoice_id, settlement)
        self.assertEqual(rental.deposit_held, 0)
        self.assertGreater(settlement.amount_residual, 0)
        self.assertEqual(action['res_model'], 'account.move')

        payment = self.env['account.payment'].with_user(self.user_accountant).create({
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': rental.partner_id.id,
            'amount': settlement.amount_residual,
            'date': fields.Date.today(),
            'journal_id': self.company.cr_cash_journal_id.id,
            'payment_reference': 'SETTLEMENT-SHORTFALL',
        })
        payment.action_post()
        receivable = settlement.line_ids.filtered(
            lambda line: line.account_id.account_type == 'asset_receivable')
        payment_lines = payment.move_id.line_ids.filtered(
            lambda line: line.account_id.account_type == 'asset_receivable')
        (receivable + payment_lines).reconcile()
        self.assertTrue(self.company.currency_id.is_zero(settlement.amount_residual))
        self.assertEqual(journey.step, 'settlement')

    def test_damage_settlement_retains_charge_and_refunds_remaining_deposit(self):
        journey = self._new_journey()
        rental = self._to_agreement(journey)
        self._sign_agreement(rental)
        self._pay_invoice(journey, user=self.user_accountant)
        self._complete_pickup_inspection(rental)
        journey.action_handover()
        journey.action_begin_return()
        self._complete_return_inspection(
            rental, new_damage=True, damage_notes='Damaged mirror')
        journey.action_continue()
        damage = rental.damage_ids.filtered(lambda case: case.state == 'draft')
        damage.write({'cost': rental.deposit_required / 2})
        damage.with_user(self.user_manager).action_approve()
        journey.with_user(self.user_accountant).action_continue()

        settlement = rental.invoice_ids.filtered(
            lambda move: move.rental_invoice_kind == 'settlement')
        self.assertEqual(len(settlement), 1)
        self.assertTrue(self.company.currency_id.is_zero(settlement.amount_residual))
        self.assertEqual(rental.deposit_held, 0)
        self.assertEqual(
            self._account_balance(rental.partner_id, self.company.cr_deposit_account_id), 0)
        refunds = rental.deposit_transaction_ids.filtered(
            lambda event: event.kind == 'refund' and event.state == 'posted')
        self.assertTrue(refunds)
        self.assertGreater(sum(refunds.mapped('amount')), 0)

    def test_return_charge_popup_captures_cleaning_and_late_products(self):
        self.company.rental_late_grace_hours = 0
        self.company.cr_cleaning_product_id.list_price = 40
        self.company.cr_late_product_id.list_price = 30
        self.company.cr_collection_product_id.list_price = 60
        journey = self._new_journey()
        journey.booking_pickup_datetime = fields.Datetime.now() - timedelta(days=5)
        rental = self._to_agreement(journey)
        self._sign_agreement(rental)
        self._pay_invoice(journey, user=self.user_accountant)
        self._complete_pickup_inspection(rental, clean=True)
        journey.action_handover()
        journey.action_begin_return()
        journey.return_collection_service = True
        self._complete_return_inspection(
            rental, clean=False, checked_on=fields.Datetime.now(), new_damage=False)
        wizard = self.env['car.rental.return.charge.wizard'].with_context(
            default_rental_id=rental.id).create({})
        self.assertTrue(wizard.cleaning_required)
        self.assertGreater(wizard.late_days, 0)
        self.assertEqual(wizard.cleaning_charge, 40)
        self.assertEqual(wizard.late_unit_price, 30)
        self.assertEqual(wizard.late_charge, wizard.late_days * 30)
        self.assertTrue(wizard.collection_service)
        self.assertEqual(wizard.collection_fee, 60)
        wizard.write({
            'cleaning_charge': 55,
            'late_unit_price': 35,
            'collection_address': 'Customer home, Maun',
            'collection_fee': 70,
        })
        wizard.action_confirm()
        self.assertEqual(journey.step, 'settlement')
        self.assertEqual(rental.cleaning_charge, 55)
        self.assertEqual(rental.late_charge, wizard.late_days * 35)
        self.assertEqual(rental.return_collection_address, 'Customer home, Maun')
        self.assertEqual(rental.return_collection_fee, 70)
        journey.with_user(self.user_accountant).action_continue()
        invoice = rental.invoice_ids.filtered(
            lambda move: move.rental_invoice_kind == 'settlement')
        charges = invoice.invoice_line_ids.filtered('rental_charge_kind')
        self.assertEqual(
            set(charges.mapped('rental_charge_kind')), {'cleaning', 'late', 'collection'})
        self.assertEqual(
            set(charges.mapped('product_id').ids),
            {
                self.company.cr_cleaning_product_id.id,
                self.company.cr_late_product_id.id,
                self.company.cr_collection_product_id.id,
            })
        self.assertEqual(invoice.amount_total, 55 + wizard.late_charge + 70)

    def test_return_collection_alone_opens_popup_and_is_in_settlement(self):
        self.company.cr_collection_product_id.list_price = 60
        journey = self._new_journey()
        rental = self._to_agreement(journey)
        self._sign_agreement(rental)
        self._pay_invoice(journey, user=self.user_accountant)
        self._complete_pickup_inspection(rental)
        journey.action_handover()
        journey.action_begin_return()
        journey.return_collection_service = True
        self._complete_return_inspection(
            rental, clean=True, checked_on=fields.Datetime.now(), new_damage=False)

        action = journey.action_continue()
        self.assertEqual(action['res_model'], 'car.rental.return.charge.wizard')
        wizard = self.env['car.rental.return.charge.wizard'].with_context(
            default_rental_id=rental.id).create({
                'collection_address': 'Customer home',
                'collection_fee': 60,
            })
        wizard.action_confirm()
        self.assertEqual(journey.step, 'settlement')
        journey.with_user(self.user_accountant).action_continue()

        invoice = rental.invoice_ids.filtered(
            lambda move: move.rental_invoice_kind == 'settlement')
        collection_line = invoice.invoice_line_ids.filtered(
            lambda line: line.rental_charge_kind == 'collection')
        self.assertEqual(len(collection_line), 1)
        self.assertEqual(collection_line.product_id, self.company.cr_collection_product_id)
        self.assertEqual(collection_line.price_subtotal, 60)

    def test_returned_dirty_car_is_not_charged_if_pickup_was_not_clean(self):
        journey = self._new_journey()
        rental = self._to_agreement(journey)
        self._sign_agreement(rental)
        self._pay_invoice(journey, user=self.user_accountant)
        self._complete_pickup_inspection(rental, clean=False)
        journey.action_handover()
        journey.action_begin_return()
        self._complete_return_inspection(rental, clean=False)
        result = journey.action_continue()
        self.assertEqual(journey.step, 'settlement')
        self.assertNotEqual(result.get('res_model'), 'car.rental.return.charge.wizard')
        self.assertEqual(rental.cleaning_charge, 0)
