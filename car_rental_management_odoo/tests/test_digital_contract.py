import base64
import io
import json
from datetime import timedelta
from unittest.mock import patch
from types import SimpleNamespace

from werkzeug.exceptions import NotFound
from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tools import file_open
from odoo.tools.pdf import PdfReader
from odoo.tests import HttpCase
from .test_workflow import TestConnectedWorkflow
from ..controllers.digital_contract import DigitalContract
from ..models.digital_contract import CUSTOMER_FIELDS


class TestDigitalContract(TestConnectedWorkflow):
    def contract(self):
        with file_open('car_rental_management_odoo/data/city_delights_contract.pdf', 'rb') as source:
            self.env.company.write({'cr_contract_pdf': base64.b64encode(source.read()), 'cr_contract_version': 'Test version'})
        rental = self.rental()
        contract = self.env['car.rental.contract'].browse(rental.action_digital_contract()['res_id'])
        contract.write({'delivery_place': 'Office', 'company_email': 'office@example.test',
                        'company_representative': 'Director', 'company_witness_1': 'CW One',
                        'company_witness_2': 'CW Two', 'renter_witness_1': 'RW One', 'renter_witness_2': 'RW Two'})
        contract.action_prepare()
        return contract

    def signature(self):
        from PIL import Image, ImageDraw
        image = Image.new('RGB', (300, 100), 'white')
        ImageDraw.Draw(image).line([(20, 70), (120, 10), (220, 80)], fill='black', width=4)
        output = io.BytesIO()
        image.save(output, format='PNG')
        return base64.b64encode(output.getvalue()).decode()

    def particulars(self):
        return dict({key: 'Test value' for key, label in CUSTOMER_FIELDS}, email='customer@example.test', kin_email='kin@example.test')

    def test_six_signatures_lock_and_complete_original_pdf(self):
        contract = self.contract()
        self.assertEqual(len(contract.signer_ids), 6)
        renter = contract.signer_ids.filtered(lambda s: s.role == 'renter')
        other = contract.signer_ids - renter
        with self.assertRaises(ValidationError), self.cr.savepoint():
            other[0]._submit({}, self.signature())
        renter._submit(self.particulars(), self.signature())
        self.assertEqual(contract.state, 'signing')
        digest = contract.document_hash
        with self.assertRaises(ValidationError), self.cr.savepoint():
            contract.write({'delivery_place': 'Changed'})
        for signer in other:
            signer._submit({}, self.signature())
        self.assertEqual(contract.state, 'complete')
        self.assertEqual(contract.rental_id.agreement_state, 'signed')
        self.assertTrue(all(s.signed_hash == digest for s in contract.signer_ids))
        reader = PdfReader(io.BytesIO(base64.b64decode(contract.completed_pdf)))
        self.assertGreater(len(reader.pages), 10)
        self.assertIn('MEMORANDUM', reader.pages[0].extract_text())
        self.assertEqual(contract.rental_id.action_print_agreement()['type'], 'ir.actions.act_url')

    def test_token_rejection_expiry_and_revocation(self):
        contract = self.contract()
        signer = contract.signer_ids[0]
        controller = DigitalContract()
        with patch('odoo.addons.car_rental_management_odoo.controllers.digital_contract.request', SimpleNamespace(env=self.env)):
            self.assertEqual(controller._signer(signer.id, signer.token), signer)
            with self.assertRaises(NotFound):
                controller._signer(signer.id, 'wrong')
            contract._store({'expires_on': fields.Datetime.now() - timedelta(seconds=1)})
            with self.assertRaises(NotFound):
                controller._signer(signer.id, signer.token)
            contract.action_revoke()
            with self.assertRaises(NotFound):
                controller._signer(signer.id, signer.token)

    def test_signature_replay_and_missing_details_blocked(self):
        contract = self.contract()
        renter = contract.signer_ids.filtered(lambda s: s.role == 'renter')
        with self.assertRaises(ValidationError), self.cr.savepoint():
            renter._submit({}, self.signature())
        with self.assertRaises(ValidationError), self.cr.savepoint():
            renter._submit(self.particulars(), self.photo.decode())
        renter._submit(self.particulars(), self.signature())
        with self.assertRaises(ValidationError), self.cr.savepoint():
            renter._submit(self.particulars(), self.signature())
        with self.assertRaises(ValidationError), self.cr.savepoint():
            contract.rental_id.action_sign_agreement()

    def test_template_is_snapshotted_and_fields_are_protected(self):
        contract = self.contract()
        original = contract.source_hash
        self.env.company.cr_contract_version = 'New template version'
        self.assertEqual(contract.template_version, 'Test version')
        self.assertEqual(contract.source_hash, original)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            contract.write({'customer_details': '{}'})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            contract.signer_ids[0].write({'signed_on': fields.Datetime.now()})


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
        self.assertEqual(self.url_open(path + '/pdf/original').status_code, 200)
        self.assertEqual(self.url_open('/rental/contract/%s/wrong' % signer.id).status_code, 404)
        # A token alone cannot bypass the form's CSRF validation.
        self.assertEqual(self.url_open(path, data={'accept': 'yes'}).status_code, 400)
        csrf = html.fromstring(response.content).xpath('//input[@name="csrf_token"]/@value')[0]
        values = dict(self.particulars(), accept='yes', signature=self.signature(), csrf_token=csrf)
        signed = self.url_open(path, data=values)
        self.assertEqual(signed.status_code, 200)
        self.assertIn('Your signature was recorded', signed.text)
