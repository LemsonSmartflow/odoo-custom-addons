"""Tests for reusable rental agreement templates and faithful PDF generation."""
import base64
import io
from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import HttpCase, tagged
from odoo.tools.pdf import PdfReader

from .common import RentalTestCommon


@tagged('post_install', '-at_install')
class TestRentalAgreementTemplate(RentalTestCommon):

    def _agreement(self):
        reservation = self._make_reservation(confirm=True)
        rental = self._make_rental(reservation)
        template = self.env['rental.agreement.template'].search([
            ('company_id', '=', self.company.id), ('state', '=', 'active')], limit=1)
        journey = rental.reservation_id.action_booking_journey()
        journey = self.env['car.rental.journey'].browse(journey['res_id'])
        agreement = self.env['rental.agreement'].create({
            'rental_id': rental.id,
            'delivery_place': 'Gaborone',
            'company_email': 'office@example.com',
            'payment_advance_days': 2,
        })
        agreement._snapshot_template(template, template._prepare_values(rental, journey))
        return agreement, template, rental

    def test_default_template_installed_with_field_mapping(self):
        template = self.env['rental.agreement.template'].search([
            ('company_id', '=', self.company.id), ('state', '=', 'active')], limit=1)
        self.assertTrue(template)
        self.assertEqual(template.name, 'City Delights Standard Rental Agreement')
        self.assertTrue(template.master_pdf)
        self.assertGreaterEqual(len(template.field_ids), 30)
        self.assertIn('renter_name', template.field_ids.mapped('key'))

    def test_values_resolved_from_partner_and_vehicle(self):
        agreement, template, rental = self._agreement()
        values = template._prepare_values(rental)
        self.assertEqual(values['renter_name'], rental.partner_id.display_name)
        self.assertEqual(values['identity_number'], rental.partner_id.rental_identity_number)
        self.assertEqual(values['vehicle_registration'], rental.vehicle_id.license_plate)
        self.assertEqual(values['lease_period'], rental.reservation_id.number_of_days)
        self.assertEqual(values['daily_rental'], rental.reservation_id.quoted_daily_rate)

    def test_generate_uses_template_and_preserves_snapshot(self):
        agreement, template, rental = self._agreement()
        before = (agreement.values_snapshot, agreement.template_config_snapshot,
                  agreement.template_master_hash)
        agreement.action_generate()
        self.assertEqual(agreement.contract_id.state, 'sent')
        self.assertEqual(agreement.contract_id.source_hash, template.master_hash)
        self.assertEqual(agreement.contract_id.template_version, template.version)
        self.assertTrue(agreement.contract_id.signer_ids)
        # Editing the template cannot rewrite an issued agreement.
        template.write({'version': 'changed', 'acceptance_text': 'changed'})
        agreement.invalidate_recordset()
        self.assertEqual(
            (agreement.values_snapshot, agreement.template_config_snapshot,
             agreement.template_master_hash), before)

    def test_required_values_block_generation(self):
        agreement, template, rental = self._agreement()
        import json
        values = json.loads(agreement.values_snapshot)
        values['renter_name'] = False
        agreement._store_agreement({'values_snapshot': json.dumps(values)})
        with self.assertRaisesRegex(ValidationError, 'Renter full legal name'):
            agreement.action_generate()

    def test_qweb_report_is_ten_pages_and_keeps_legal_clauses(self):
        agreement, template, rental = self._agreement()
        agreement.action_generate()
        report = self.env.ref(
            'car_rental_management_odoo.action_report_city_delights_agreement')
        rendered, report_type = self.env['ir.actions.report']._render_qweb_pdf(
            report.get_external_id()[report.id], [agreement.id])
        if report_type == 'pdf':
            pdf = rendered if isinstance(rendered, bytes) else b''.join(
                stream.getvalue() for stream in rendered.values())
            reader = PdfReader(io.BytesIO(pdf))
            self.assertEqual(len(reader.pages), 10)
            text = '\n'.join(page.extract_text() or '' for page in reader.pages)
        else:
            # Some test environments render HTML when wkhtmltopdf is unavailable.
            text = rendered.decode('utf-8', 'ignore') if isinstance(rendered, bytes) else str(rendered)
            self.assertEqual(text.count('<div class="cd-page"'), 10)
        for clause in ('MEMORANDUM OF AGREEMENT OF LEASE', 'FIRST SCHEDULE',
                       'SECOND SCHEDULE', 'THIRD SCHEDULE',
                       'laws of the Republic of Botswana', '62923303599'):
            self.assertIn(clause, text)
        self.assertIn(rental.partner_id.display_name, text)
        self.assertIn(rental.vehicle_id.license_plate, text)

    def test_multiple_agreements_from_one_template_are_independent(self):
        first, template, _rental = self._agreement()
        second, template2, _rental2 = self._agreement()
        self.assertEqual(template, template2)
        self.assertNotEqual(first.id, second.id)
        first.action_generate()
        self.assertEqual(second.contract_id.state, 'draft')
        first._store_agreement({'values_snapshot': '{}'})
        self.assertTrue(second.values_snapshot)
