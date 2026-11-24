"""Odoo Sign implementation of the rental signing gateway (Enterprise only).

This addon is intentionally separate: the core car rental module must remain
installable on Community without any sign.* reference.
"""
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class SignGatewayBridge(models.Model):
    _inherit = 'car.rental.sign.gateway'

    @api.model
    def is_ready(self):
        return bool(self.env['ir.module.module'].sudo().search_count([
            ('name', '=', 'sign'), ('state', '=', 'installed')]))

    @api.model
    def prepare(self, contract):
        """Create an immutable sign template for this agreement version."""
        attachment = self.env['ir.attachment'].create({
            'name': contract.source_filename or 'rental-agreement.pdf',
            'datas': contract.source_pdf,
            'mimetype': 'application/pdf',
            'res_model': 'car.rental.contract',
            'res_id': contract.id,
        })
        template = self.env['sign.template'].create({
            'name': '%s - %s' % (contract.rental_id.reference,
                                contract.template_version or 'v1'),
        })
        self.env['sign.document'].create({
            'template_id': template.id,
            'attachment_id': attachment.id,
        })
        contract._store({'external_request_ref': 'sign.template,%s' % template.id,
                         'sign_state': 'prepared'})
        return True

    @api.model
    def send(self, contract):
        """Create and send a sign request to the renter."""
        ref = (contract.external_request_ref or '').split(',')
        if len(ref) != 2 or ref[0] != 'sign.template':
            self.prepare(contract)
            ref = (contract.external_request_ref or '').split(',')
        template = self.env['sign.template'].browse(int(ref[-1]))
        SignRequest = self.env['sign.request']
        # Odoo 19 exposes the create/send flow through sign.send.request.
        send_model = 'sign.send.request' if 'sign.send.request' in self.env else False
        if send_model:
            wizard = self.env[send_model].create({
                'template_id': template.id,
                'subject': 'Rental agreement %s' % contract.rental_id.reference,
                'filename': 'rental-agreement.pdf',
                'signers_count': 1,
            })
            wizard.send_request()
            request = getattr(wizard, 'sign_request_id', SignRequest)
        else:  # fallback for older Sign versions
            request = SignRequest.create({
                'template_id': template.id,
                'reference': contract.rental_id.reference,
            })
            request.action_sent()
        contract._store({
            'external_request_ref': 'sign.request,%s' % request.id,
            'sign_state': 'sent',
        })
        return True

    @api.model
    def sync(self, contract):
        ref = (contract.external_request_ref or '').split(',')
        if len(ref) != 2 or ref[0] != 'sign.request':
            return False
        request = self.env['sign.request'].browse(int(ref[-1])).exists()
        if not request:
            return False
        field = next((name for name in ('completed_file', 'completed_pdf')
                      if name in request._fields), None)
        if field and request[field] and contract.state != 'complete':
            contract.complete_from_external(
                request[field], request.create_uid.display_name, fields.Datetime.now())
        else:
            contract._store({'sign_state': request.state})
        return True

    @api.model
    def cancel(self, contract):
        ref = (contract.external_request_ref or '').split(',')
        if len(ref) == 2 and ref[0] == 'sign.request':
            request = self.env['sign.request'].browse(int(ref[-1])).exists()
            if request and hasattr(request, 'action_cancel'):
                request.action_cancel()
        contract._store({'sign_state': 'cancelled'})
        return True


class ContractSignLink(models.Model):
    _inherit = 'car.rental.contract'

    sign_request_id = fields.Many2one('sign.request', readonly=True, copy=False)
