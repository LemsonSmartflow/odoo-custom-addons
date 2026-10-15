import base64
import secrets

from werkzeug.exceptions import NotFound
from odoo import fields, http
from odoo.http import request
from odoo.exceptions import ValidationError
from ..models.digital_contract import CUSTOMER_FIELDS, ROLES


class DigitalContract(http.Controller):
    def _signer(self, signer_id, token):
        signer = request.env['car.rental.contract.signer'].sudo().browse(signer_id).exists()
        if not signer or not token or not secrets.compare_digest(signer.token or '', token):
            raise NotFound()
        contract = signer.contract_id
        if contract.state == 'cancelled' or not contract.expires_on or contract.expires_on < fields.Datetime.now():
            raise NotFound()
        return signer

    def _private(self, response):
        response.headers.update({'Cache-Control': 'no-store, private', 'Referrer-Policy': 'no-referrer',
                                 'X-Robots-Tag': 'noindex, nofollow', 'X-Content-Type-Options': 'nosniff',
                                 'X-Frame-Options': 'DENY'})
        return response

    @http.route('/rental/contract/<int:signer_id>/<string:token>', type='http', auth='public', methods=['GET', 'POST'], sitemap=False)
    def contract(self, signer_id, token, **post):
        signer = self._signer(signer_id, token)
        contract = signer.contract_id
        error = None
        if request.httprequest.method == 'POST':
            try:
                if post.get('accept') != 'yes':
                    raise ValidationError('Confirm you have read the original contract and completed schedule.')
                with request.env.cr.savepoint():
                    signer._submit(post, post.get('signature', ''))
            except ValidationError as exc:
                error = str(exc)
        import json
        values = contract._prefill()
        if error and signer.role == 'renter':
            values.update({key: str(post.get(key, values.get(key, '')))[:2000] for key, label in CUSTOMER_FIELDS})
        response = request.render('car_rental_management_odoo.digital_contract_page', {
            'signer': signer, 'contract': contract, 'token': token, 'error': error,
            'customer_fields': CUSTOMER_FIELDS, 'values': values,
            'schedule': json.loads(contract.snapshot or '{}'), 'role_label': dict(ROLES)[signer.role],
            'can_sign': not signer.signed_on and contract.rental_id.status == 'draft' and
                        (signer.role == 'renter' and contract.state == 'sent' or signer.role != 'renter' and contract.state == 'signing')})
        return self._private(response)

    @http.route('/rental/contract/<int:signer_id>/<string:token>/pdf/<string:kind>', type='http', auth='public', methods=['GET'], sitemap=False)
    def pdf(self, signer_id, token, kind, **kwargs):
        signer = self._signer(signer_id, token)
        contract = signer.contract_id
        if kind == 'original':
            data = base64.b64decode(contract.source_pdf)
        elif kind == 'completed' and contract.state == 'complete':
            data = base64.b64decode(contract.completed_pdf)
        elif kind == 'review' and contract.state in ('signing', 'complete'):
            data = contract._pdf()
        else:
            raise NotFound()
        return self._private(request.make_response(data, headers=[('Content-Type', 'application/pdf'),
                        ('Content-Disposition', 'inline; filename="rental-contract.pdf"')]))
