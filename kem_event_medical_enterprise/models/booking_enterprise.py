"""Enterprise synchronisation for event bookings.

The core addon calls the `_enterprise_*` hooks. This bridge implements them
using Planning, Documents and Sign. Every enterprise access is guarded so a
missing app can never break the core workflow.
"""
import base64
import logging
from datetime import datetime, time

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class KemEventBooking(models.Model):
    _inherit = 'kem.event.booking'

    planning_slot_ids = fields.One2many('planning.slot', 'kem_booking_id', string='Planning Slots')
    fieldservice_task_ids = fields.One2many('project.task', 'kem_booking_id', string='Field Service Tasks')
    documents_document_ids = fields.One2many('documents.document', 'kem_booking_id', string='Documents App Files')
    sign_request_id = fields.Many2one('sign.request', 'Signature Request', readonly=True, copy=False)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @api.model
    def _kem_module_installed(self, name):
        return bool(self.env['ir.module.module'].sudo().search_count([
            ('name', '=', name), ('state', '=', 'installed')
        ]))

    def _kem_documents_folder(self):
        Folder = self.env['documents.folder'].sudo()
        folder = Folder.search([('name', '=', 'Event Medical Services')], limit=1)
        if not folder:
            values = {'name': 'Event Medical Services'}
            if 'company_id' in Folder._fields:
                values['company_id'] = self.company_id.id
            folder = Folder.create(values)
        return folder

    def _kem_ensure_document(self, name, res_model=None, res_id=None):
        if not self._kem_module_installed('documents'):
            return False
        Document = self.env['documents.document'].sudo()
        fields_map = Document._fields
        vals = {
            'name': name,
            'folder_id': self._kem_documents_folder().id,
            'kem_booking_id': self.id,
        }
        if 'company_id' in fields_map:
            vals['company_id'] = self.company_id.id
        if res_model and 'res_model' in fields_map:
            vals.update({'res_model': res_model, 'res_id': res_id})
        return Document.create(vals)

    @api.model
    def _kem_combine(self, date_value, text, default):
        if not date_value:
            return False
        try:
            hour, minute = [int(part) for part in (text or '').split(':')[:2]]
            clock = time(hour, minute)
        except (ValueError, TypeError):
            clock = default
        return datetime.combine(date_value, clock)

    @api.model
    def _kem_simple_pdf(self, text):
        """A tiny valid PDF used as the template source for a demo agreement."""
        safe = ''.join(ch for ch in (text or 'Booking agreement') if 32 <= ord(ch) < 127)[:90]
        content = ('BT /F1 13 Tf 60 760 Td (%s) Tj ET' % safe).encode('ascii')
        objects = [
            b'<< /Type /Catalog /Pages 2 0 R >>',
            b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
            b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] '
            b'/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>',
            b'<< /Length %d >>\nstream\n' % len(content) + content + b'\nendstream',
            b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
        ]
        out = bytearray(b'%PDF-1.4\n')
        offsets = []
        for number, obj in enumerate(objects, 1):
            offsets.append(len(out))
            out += ('%d 0 obj\n' % number).encode('ascii') + obj + b'\nendobj\n'
        xref_at = len(out)
        out += ('xref\n0 %d\n' % (len(objects) + 1)).encode('ascii')
        out += b'0000000000 65535 f \n'
        for offset in offsets:
            out += ('%010d 00000 n \n' % offset).encode('ascii')
        out += ('trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n'
                % (len(objects) + 1, xref_at)).encode('ascii')
        return base64.b64encode(bytes(out)).decode('ascii')

    # ------------------------------------------------------------------
    # Core hooks
    # ------------------------------------------------------------------
    def _enterprise_on_confirm(self):
        for booking in self:
            booking._kem_ensure_document(
                'Booking confirmation — %s' % booking.reference,
                'kem.event.booking', booking.id,
            )
        return True

    def _enterprise_create_planning_slots(self):
        if not self._kem_module_installed('planning'):
            return True
        Slot = self.env['planning.slot'].sudo()
        for booking in self:
            start = booking._kem_combine(booking.start_date, booking.service_start, time(8, 0))
            end = booking._kem_combine(booking.end_date or booking.start_date,
                                       booking.service_end, time(18, 0))
            for employee in booking.team_ids.filtered('resource_id'):
                exists = Slot.search([
                    ('kem_booking_id', '=', booking.id),
                    ('resource_id', '=', employee.resource_id.id),
                ], limit=1)
                if exists:
                    continue
                vals = {
                    'name': booking.name,
                    'resource_id': employee.resource_id.id,
                    'start_datetime': start,
                    'end_datetime': end,
                    'kem_booking_id': booking.id,
                }
                if 'company_id' in Slot._fields:
                    vals['company_id'] = booking.company_id.id
                if 'role_id' in Slot._fields and employee.job_id:
                    role = self.env['planning.role'].sudo().search(
                        [('name', '=', employee.job_id.name)], limit=1)
                    if role:
                        vals['role_id'] = role.id
                Slot.create(vals)
        return True

    def _enterprise_on_complete(self):
        for booking in self:
            booking._kem_ensure_document(
                'Service report — %s' % booking.reference,
                'kem.event.booking', booking.id,
            )
            if booking.sign_request_id:
                booking.action_refresh_sign_status()
        return True

    # ------------------------------------------------------------------
    # Odoo Sign
    # ------------------------------------------------------------------
    def _kem_prepare_sign_template(self):
        self.ensure_one()
        if not self._kem_module_installed('sign'):
            raise UserError('Odoo Sign is not installed on this database.')
        attachment = self.env['ir.attachment'].sudo().create({
            'name': '%s agreement.pdf' % self.reference,
            'datas': self._kem_simple_pdf('Event Medical Booking Agreement - %s' % self.name),
            'mimetype': 'application/pdf',
            'res_model': 'kem.event.booking',
            'res_id': self.id,
        })
        template = self.env['sign.template'].sudo().create({
            'name': 'Booking agreement — %s' % self.reference,
        })
        self.env['sign.document'].sudo().create({
            'template_id': template.id,
            'attachment_id': attachment.id,
        })
        self.message_post(body='Signature template prepared in Odoo Sign.')
        return template

    def action_send_for_signature(self):
        """Send the booking confirmation agreement for digital signing."""
        SignRequest = self.env['sign.request'].sudo()
        for booking in self:
            if not booking.partner_id.email:
                raise UserError('The customer needs an email address before sending for signature.')
            template = booking._kem_prepare_sign_template()
            send_model = 'sign.send.request' if 'sign.send.request' in self.env else False
            if send_model:
                wizard = self.env[send_model].sudo().create({
                    'template_id': template.id,
                    'subject': 'Booking agreement %s' % booking.reference,
                    'filename': 'booking-agreement.pdf',
                    'signers_count': 1,
                })
                wizard.send_request()
                request = getattr(wizard, 'sign_request_id', SignRequest)
            else:  # fallback for older Sign versions
                request = SignRequest.create({
                    'template_id': template.id,
                    'reference': booking.reference,
                })
                request.action_sent()
            booking.sign_request_id = request
            booking.message_post(body='Booking agreement sent for signature via Odoo Sign.')
        return True

    def action_refresh_sign_status(self):
        for booking in self:
            request = booking.sign_request_id.exists()
            if not request:
                continue
            field = next((name for name in ('completed_file', 'completed_pdf')
                          if name in request._fields), None)
            if field and request[field]:
                booking._kem_ensure_document(
                    'Signed agreement — %s' % booking.reference,
                    'kem.event.booking', booking.id,
                )
                booking.message_post(body='Signed agreement received (%s).' % request.state)
            else:
                booking.message_post(body='Sign status: %s' % request.state)
        return True

    # ------------------------------------------------------------------
    # Cross-app navigation
    # ------------------------------------------------------------------
    def action_view_planning_slots(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Planning — %s' % self.reference,
            'res_model': 'planning.slot',
            'view_mode': 'gantt,list,form',
            'domain': [('kem_booking_id', '=', self.id)],
            'context': {'default_kem_booking_id': self.id},
        }

    def action_view_fieldservice_tasks(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Field Service — %s' % self.reference,
            'res_model': 'project.task',
            'view_mode': 'list,form,kanban',
            'domain': [('kem_booking_id', '=', self.id)],
            'context': {'default_kem_booking_id': self.id, 'default_project_id': self.project_id.id},
        }

    def action_view_documents_app(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Documents — %s' % self.reference,
            'res_model': 'documents.document',
            'view_mode': 'list,form',
            'domain': [('kem_booking_id', '=', self.id)],
        }
