"""Digital contract token, signature and original-PDF locking tests.

Re-authored against the 19.0.8.0.0 standard-model architecture: rentals are
built on res.partner / fleet.vehicle through RentalTestCommon, and the
customer particulars come from the res.partner-backed CUSTOMER_FIELDS set.
"""
import base64
import io
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from werkzeug.exceptions import NotFound

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import HttpCase, tagged
from odoo.tools import file_open
from odoo.tools.pdf import PdfReader

from ..controllers.digital_contract import DigitalContract
from .common import PNG_IMAGE, PNG_SIGNATURE, RentalTestCommon


@tagged('post_install', '-at_install')
class TestDigitalContract(RentalTestCommon):

    def contract(self):
        with file_open('car_rental_management_odoo/data/city_delights_contract.pdf', 'rb') as source:
            self.company.write({'cr_contract_pdf': base64.b64encode(source.read()),
                                'cr_contract_version': 'Test version'})
        rental = self._make_rental(self._make_reservation())
        contract = self.env['car.rental.contract'].browse(rental.action_digital_contract()['res_id'])
        contract.write({'delivery_place': 'Office', 'company_email': 'office@example.test',
                        'company_representative': 'Director', 'company_witness_1': 'CW One',
                        'company_witness_2': 'CW Two', 'renter_witness_1': 'RW One', 'renter_witness_2': 'RW Two'})
        contract.action_prepare()
        return contract

    def particulars(self):
        return {'signed_at_place': 'Gaborone'}

    def test_six_signatures_lock_and_complete_original_pdf(self):
        contract = self.contract()
        self.assertEqual(len(contract.signer_ids), 6)
        renter = contract.signer_ids.filtered(lambda s: s.role == 'renter')
        other = contract.signer_ids - renter
        with self.assertRaises(ValidationError), self.cr.savepoint():
            other[0]._submit({}, PNG_SIGNATURE)
        renter._submit(self.particulars(), PNG_SIGNATURE)
        self.assertEqual(contract.state, 'signing')
        digest = contract.document_hash
        with self.assertRaises(ValidationError), self.cr.savepoint():
            contract.write({'delivery_place': 'Changed'})
        for signer in other:
            signer._submit({}, PNG_SIGNATURE)
        self.assertEqual(contract.state, 'complete')
        self.assertEqual(contract.rental_id.agreement_state, 'signed')
        self.assertTrue(all(s.signed_hash == digest for s in contract.signer_ids))
        reader = PdfReader(io.BytesIO(base64.b64decode(contract.completed_pdf)))
        self.assertGreater(len(reader.pages), 10)
        self.assertIn('MEMORANDUM', reader.pages[0].extract_text())
        self.assertEqual(contract.rental_id.action_print_agreement()['type'], 'ir.actions.act_url')

    def test_customer_only_agreement_completes_without_optional_signers(self):
        with file_open('car_rental_management_odoo/data/city_delights_contract.pdf', 'rb') as source:
            self.company.write({'cr_contract_pdf': base64.b64encode(source.read()),
                                'cr_contract_version': 'Test version'})
        rental = self._make_rental(self._make_reservation())
        contract = self.env['car.rental.contract'].browse(
            rental.action_digital_contract()['res_id'])
        contract.write({'delivery_place': 'Office', 'company_email': 'office@example.test'})
        contract.action_prepare()

        self.assertEqual(len(contract.signer_ids), 1)
        snapshot = contract._prefill()
        self.assertEqual(snapshot['full_name'], rental.partner_id.display_name)
        self.assertEqual(snapshot['next_of_kin'], rental.partner_id.rental_next_of_kin_name)
        self.assertEqual(snapshot['relationship'], rental.partner_id.rental_next_of_kin_relationship)
        self.assertEqual(snapshot['kin_phone'], rental.partner_id.rental_next_of_kin_phone)
        renter = contract.signer_ids.filtered(lambda signer: signer.role == 'renter')
        renter._submit(dict(self.particulars(), full_name='Tampered Customer'), PNG_SIGNATURE)

        self.assertEqual(contract.state, 'complete')
        self.assertEqual(rental.agreement_state, 'signed')
        self.assertEqual(contract._prefill()['full_name'], rental.partner_id.display_name)
        self.assertEqual(contract._prefill()['signed_at_place'], 'Gaborone')

    def test_completion_failure_shows_safe_message_and_rolls_back_signature(self):
        contract = self.contract()
        renter = contract.signer_ids.filtered(lambda signer: signer.role == 'renter')

        with self.assertRaisesRegex(ValidationError, 'problem at the rental office') as raised:
            with self.cr.savepoint():
                with patch.object(
                    type(contract), '_finish',
                    side_effect=ValidationError(
                        'Configure rental income accounts and the sales journal in Car Rental Settings first.'),
                ), patch(
                    'odoo.addons.car_rental_management_odoo.models.digital_contract._logger.exception'
                ):
                    renter._submit(self.particulars(), PNG_SIGNATURE)

        self.assertNotIn('Configure rental income accounts', str(raised.exception))
        contract.invalidate_recordset()
        renter.invalidate_recordset()
        self.assertEqual(contract.state, 'sent')
        self.assertFalse(renter.signed_on)
        self.assertFalse(contract.customer_details)

    def test_token_rejection_expiry_and_revocation(self):
        contract = self.contract()
        signer = contract.signer_ids[0]
        controller = DigitalContract()
        with patch('odoo.addons.car_rental_management_odoo.controllers.digital_contract.request',
                   SimpleNamespace(env=self.env)):
            self.assertEqual(controller._signer(signer.id, signer.token), signer)
            with self.assertRaises(NotFound):
                controller._signer(signer.id, 'wrong')
            contract._store({'expires_on': fields.Datetime.now() - timedelta(seconds=1)})
            with self.assertRaises(NotFound):
                controller._signer(signer.id, signer.token)
            contract.action_revoke()
            with self.assertRaises(NotFound):
                controller._signer(signer.id, signer.token)

    def test_expired_unsigned_agreement_can_be_renewed_by_a_manager(self):
        with file_open('car_rental_management_odoo/data/city_delights_contract.pdf', 'rb') as source:
            self.company.write({'cr_contract_pdf': base64.b64encode(source.read()),
                                'cr_contract_version': 'Test version'})
        category = self._make_category()
        zone = self._make_zone()
        self._make_rate_rule(category, zone)
        vehicle = self._make_vehicle(category=category)
        journey = self.env['car.rental.journey'].create({
            'company_id': self.company.id,
            'booking_partner_id': self._make_partner().id,
            'booking_destination_id': zone.id,
            'booking_category_id': category.id,
            'booking_vehicle_id': vehicle.id,
            'booking_pickup_datetime': fields.Datetime.now() + timedelta(days=2),
            'booking_number_of_days': 2,
        })
        journey.action_continue()
        journey.action_continue()
        journey.agreement_company_email = 'office@example.test'
        journey.agreement_delivery_place = 'Office'
        contract = journey._prepare_agreement_signing_link()
        renter = contract.signer_ids.filtered(lambda signer: signer.role == 'renter')
        old_link = renter.link
        contract._store({'expires_on': fields.Datetime.now() - timedelta(seconds=1)})
        journey.invalidate_recordset(['agreement_contract_state', 'agreement_signing_url'])
        self.assertEqual(journey.agreement_contract_state, 'expired')
        self.assertFalse(journey.agreement_signing_url)

        send_action = journey.action_send_agreement()
        self.assertEqual(send_action['res_model'], 'car.rental.agreement.send.wizard')
        wizard = self.env[send_action['res_model']].create({
            'journey_id': journey.id,
            'method': 'email',
        })
        self.env['ir.config_parameter'].sudo().set_param(
            'web.base.url', 'https://rental.example.com')
        with self.assertRaises(ValidationError), self.cr.savepoint():
            wizard.action_send()
        journey.with_user(self.user_manager).action_renew_expired_agreement()

        replacement = journey.rental_id.contract_ids.filtered(lambda item: item.state == 'sent')
        new_renter = replacement.signer_ids.filtered(lambda signer: signer.role == 'renter')
        self.assertEqual(contract.state, 'cancelled')
        self.assertEqual(len(replacement), 1)
        self.assertNotEqual(new_renter.link, old_link)
        self.assertEqual(journey.agreement_contract_state, 'sent')

    def test_signature_replay_and_missing_details_blocked(self):
        contract = self.contract()
        renter = contract.signer_ids.filtered(lambda s: s.role == 'renter')
        with self.assertRaises(ValidationError), self.cr.savepoint():
            renter._submit({}, PNG_SIGNATURE)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            renter._submit(self.particulars(), PNG_IMAGE)
        renter._submit(self.particulars(), PNG_SIGNATURE)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            renter._submit(self.particulars(), PNG_SIGNATURE)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            contract.rental_id.action_sign_agreement()

    def test_template_is_snapshotted_and_fields_are_protected(self):
        contract = self.contract()
        original = contract.source_hash
        self.company.cr_contract_version = 'New template version'
        self.assertEqual(contract.template_version, 'Test version')
        self.assertEqual(contract.source_hash, original)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            contract.write({'customer_details': '{}'})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            contract.signer_ids[0].write({'signed_on': fields.Datetime.now()})


@tagged('post_install', '-at_install')
class TestDigitalContractHttp(TestDigitalContract, HttpCase):

    def test_customer_page_pdf_and_csrf(self):
        from lxml import html
        contract = self.contract()
        signer = contract.signer_ids.filtered(lambda s: s.role == 'renter')
        path = '/rental/contract/%s/%s' % (signer.id, signer.token)
        response = self.url_open(path)
        self.assertEqual(response.status_code, 200)
        self.assertIn('no-store', response.headers['Cache-Control'])
        self.assertIn('Next of kin', response.text)
        self.assertIn('name="signed_at_place"', response.text)
        self.assertNotIn('name="full_name"', response.text)
        self.assertEqual(self.url_open(path + '/pdf/original').status_code, 200)
        self.assertEqual(self.url_open('/rental/contract/%s/wrong' % signer.id).status_code, 404)
        # A token alone cannot bypass the form's CSRF validation.
        self.assertEqual(self.url_open(path, data={'accept': 'yes'}).status_code, 400)
        csrf = html.fromstring(response.content).xpath('//input[@name="csrf_token"]/@value')[0]
        values = dict(self.particulars(), accept='yes', signature=PNG_SIGNATURE.decode(), csrf_token=csrf)
        signed = self.url_open(path, data=values)
        self.assertEqual(signed.status_code, 200)
        self.assertIn('Your signature was recorded', signed.text)
