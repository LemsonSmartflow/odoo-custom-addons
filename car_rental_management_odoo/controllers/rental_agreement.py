"""Authenticated PDF routes for issued rental agreements."""
import base64

from odoo import http
from odoo.http import request


class RentalAgreementController(http.Controller):

    @http.route('/rental/agreement/<int:agreement_id>/pdf/<string:kind>',
                type='http', auth='user', sitemap=False)
    def agreement_pdf(self, agreement_id, kind, **kwargs):
        agreement = request.env['rental.agreement'].browse(agreement_id).exists()
        if not agreement:
            return request.not_found()
        agreement.check_access_rights('read')
        agreement.check_access_rule('read')
        contract = agreement.contract_id
        if kind == 'original' and contract.source_pdf:
            data = base64.b64decode(contract.source_pdf)
            name = contract.source_filename or 'rental-agreement.pdf'
        elif kind == 'completed' and contract.completed_pdf:
            data = base64.b64decode(contract.completed_pdf)
            name = contract.completed_filename or 'signed-agreement.pdf'
        elif kind == 'review':
            report = request.env.ref(
                'car_rental_management_odoo.action_report_city_delights_agreement')
            data = request.env['ir.actions.report']._render_qweb_pdf(
                report.get_external_id()[report.id], [agreement.id])[0]
            name = 'rental-agreement-%s.pdf' % agreement.rental_id.reference
        else:
            return request.not_found()
        return request.make_response(data, [
            ('Content-Type', 'application/pdf'),
            ('Content-Disposition', 'inline; filename="%s"' % name),
            ('Cache-Control', 'no-store, private'),
        ])
