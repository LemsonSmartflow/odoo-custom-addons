"""Private, versioned contract packets and individual signature requests."""
import base64
import hashlib
import io
import json
import secrets
from datetime import timedelta
from xml.sax.saxutils import escape

from PIL import Image
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as PDFImage, Table, TableStyle, PageBreak, KeepTogether
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import file_open
from odoo.tools.pdf import merge_pdf
from .pricing import require_role

ROLES = [('renter', 'Renter'), ('company', 'Company Representative'),
         ('company_witness_1', 'Company Witness 1'), ('company_witness_2', 'Company Witness 2'),
         ('renter_witness_1', 'Renter Witness 1'), ('renter_witness_2', 'Renter Witness 2')]
CUSTOMER_FIELDS = [('full_name', 'Full legal name'), ('identity', 'Omang / Passport number'),
                   ('physical_address', 'Physical / notices address'), ('postal_address', 'Postal address'),
                   ('phone', 'Cellphone number'), ('email', 'Email address'),
                   ('licence', 'Driving licence number'), ('next_of_kin', 'Next of kin full name'),
                   ('relationship', 'Relationship'), ('kin_phone', 'Next of kin cellphone'),
                   ('kin_email', 'Next of kin email'), ('signed_at_place', 'Place of signing')]


class Company(models.Model):
    _inherit = 'res.company'
    cr_contract_pdf = fields.Binary(string='Contract PDF Template', attachment=True, groups='car_rental_management_odoo.group_rental_manager')
    cr_contract_filename = fields.Char(default='City Delights Contract.pdf')
    cr_contract_version = fields.Char(string='Contract Template Version')


class Settings(models.TransientModel):
    _inherit = 'res.config.settings'
    cr_contract_pdf = fields.Binary(related='company_id.cr_contract_pdf', readonly=False)
    cr_contract_filename = fields.Char(related='company_id.cr_contract_filename', readonly=False)
    cr_contract_version = fields.Char(related='company_id.cr_contract_version', readonly=False)

    def action_load_city_contract(self):
        require_role(self.env, 'group_rental_manager')
        self.ensure_one()
        with file_open('car_rental_management_odoo/data/city_delights_contract.pdf', 'rb') as source:
            self.company_id.write({'cr_contract_pdf': base64.b64encode(source.read()),
                                  'cr_contract_filename': 'City Delights Contract.pdf',
                                  'cr_contract_version': 'City Delights supplied contract - October 2026'})
        return {'type': 'ir.actions.client', 'tag': 'reload'}


class Rental(models.Model):
    _inherit = 'car.rental.rental'
    contract_ids = fields.One2many('car.rental.contract', 'rental_id', string='Digital Agreements')

    def action_digital_contract(self):
        self.ensure_one()
        contract = self.contract_ids.filtered(lambda c: c.state != 'cancelled')[:1]
        if not contract:
            if self.status != 'draft' or self.agreement_state == 'signed':
                raise ValidationError('Prepare the digital contract before signing or handing over the rental.')
            contract = self.env['car.rental.contract'].create({'rental_id': self.id})
        return {'type': 'ir.actions.act_window', 'name': 'Digital Agreement', 'res_model': contract._name,
                'view_mode': 'form', 'res_id': contract.id}

    def action_sign_agreement(self):
        if any(c.state not in ('complete', 'cancelled') for c in self.mapped('contract_ids')):
            raise ValidationError('Complete all digital contract signatures first.')
        return super().action_sign_agreement()

    def action_start_rental(self):
        if any(c.state not in ('complete', 'cancelled') for c in self.mapped('contract_ids')):
            raise ValidationError('Collect all six digital signatures before handover.')
        return super().action_start_rental()

    def action_print_agreement(self):
        self.ensure_one()
        contract = self.contract_ids.filtered(lambda c: c.state == 'complete')[:1]
        if contract:
            return {'type': 'ir.actions.act_url', 'url': '/web/content/car.rental.contract/%s/completed_pdf/%s?download=true' % (contract.id, 'signed-agreement.pdf'), 'target': 'new'}
        return super().action_print_agreement()


class Journey(models.Model):
    _inherit = 'car.rental.journey'

    def action_digital_contract(self):
        self.ensure_one()
        if not self.rental_id:
            raise ValidationError('Confirm the booking and create its rental first.')
        return self.rental_id.action_digital_contract()


class Reservation(models.Model):
    _inherit = 'car.rental.reservation'

    def action_refresh_cleaning_fee(self):
        if any(c.state not in ('draft', 'cancelled') for c in self.mapped('rental_ids.contract_ids')):
            raise ValidationError('The issued digital agreement locks the agreed cleaning fee. Revoke it before changing the fee.')
        return super().action_refresh_cleaning_fee()


class Contract(models.Model):
    _name = 'car.rental.contract'
    _description = 'Digital Rental Contract'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'rental_id'
    _check_company_auto = True
    rental_id = fields.Many2one('car.rental.rental', required=True, ondelete='restrict', check_company=True)
    company_id = fields.Many2one(related='rental_id.company_id', store=True)
    state = fields.Selection([('draft', 'Prepare'), ('sent', 'Awaiting Customer'), ('signing', 'Awaiting Other Signatures'),
                              ('complete', 'All Signed'), ('cancelled', 'Revoked')], default='draft', readonly=True, tracking=True)
    delivery_place = fields.Char()
    payment_advance_days = fields.Integer(string='Payment Advance Deadline (days)', required=True, default=0,
                                         help='Completes the blank in clause 6. Zero means payable by delivery.')
    company_email = fields.Char(string='Company Notices Email')
    company_representative = fields.Char()
    company_witness_1 = fields.Char()
    company_witness_2 = fields.Char()
    renter_witness_1 = fields.Char()
    renter_witness_2 = fields.Char()
    signer_ids = fields.One2many('car.rental.contract.signer', 'contract_id', readonly=True)
    source_pdf = fields.Binary(attachment=True, readonly=True)
    source_filename = fields.Char(readonly=True)
    template_version = fields.Char(readonly=True)
    source_hash = fields.Char(readonly=True)
    snapshot = fields.Text(readonly=True)
    customer_details = fields.Text(readonly=True)
    submitted_on = fields.Datetime(readonly=True)
    document_hash = fields.Char(readonly=True, string='Signed Content SHA-256')
    completed_pdf = fields.Binary(attachment=True, readonly=True)
    completed_filename = fields.Char(readonly=True)
    expires_on = fields.Datetime(readonly=True)
    particulars_html = fields.Html(compute='_compute_particulars', string='Recorded Particulars')

    @api.depends('snapshot', 'customer_details')
    def _compute_particulars(self):
        for contract in self:
            items = list(json.loads(contract.snapshot or '{}').items())
            submitted = json.loads(contract.customer_details or '{}')
            items += [(label, submitted.get(key, '')) for key, label in CUSTOMER_FIELDS]
            contract.particulars_html = '<table class="table"><tbody>%s</tbody></table>' % ''.join(
                '<tr><th>%s</th><td>%s</td></tr>' % (escape(label), escape(str('' if value is None or value is False else value)).replace('\n', '<br/>'))
                for label, value in items)

    @api.model_create_multi
    def create(self, vals_list):
        protected = {'state', 'source_pdf', 'source_hash', 'snapshot', 'customer_details', 'signer_ids',
                     'submitted_on', 'document_hash', 'completed_pdf', 'expires_on'}
        for vals in vals_list:
            if protected.intersection(vals):
                raise ValidationError('Prepare a new contract through the digital agreement workflow.')
            rental = self.env['car.rental.rental'].browse(vals.get('rental_id'))
            if rental.status != 'draft' or rental.agreement_state == 'signed':
                raise ValidationError('Only unsigned draft rentals can have a new digital agreement.')
        return super().create(vals_list)

    def write(self, vals):
        if set(vals) - {'delivery_place', 'payment_advance_days', 'company_email', 'company_representative',
                        'company_witness_1', 'company_witness_2', 'renter_witness_1', 'renter_witness_2',
                        'message_follower_ids', 'activity_ids'}:
            raise ValidationError('Use the contract actions to update its protected records.')
        if any(c.state != 'draft' for c in self):
            raise ValidationError('Issued contracts are locked. Revoke an unsigned contract and prepare a replacement.')
        return super().write(vals)

    def unlink(self):
        if any(c.state != 'draft' for c in self):
            raise ValidationError('Issued contracts are retained for the audit trail.')
        return super().unlink()

    def _store(self, vals):
        return super().write(vals)

    def _lock(self):
        self.ensure_one()
        self.env.cr.execute('SELECT id FROM car_rental_contract WHERE id=%s FOR UPDATE', [self.id])
        self.invalidate_recordset()

    def action_prepare(self):
        self.ensure_one()
        self._lock()
        if self.state != 'draft':
            raise ValidationError('This contract has already been issued.')
        rental = self.rental_id
        self.env.cr.execute('SELECT id FROM car_rental_rental WHERE id=%s FOR UPDATE', [rental.id])
        if rental.contract_ids.filtered(lambda c: c != self and c.state not in ('draft', 'cancelled')):
            raise ValidationError('Another active contract already exists for this rental.')
        company = self.company_id.sudo()
        if not company.cr_contract_pdf or not company.cr_contract_version:
            raise ValidationError('Load the contract PDF and version in Car Rental Settings first.')
        if rental.status != 'draft' or rental.agreement_state == 'signed':
            raise ValidationError('The rental must still be unsigned and awaiting pickup.')
        if self.payment_advance_days < 0:
            raise ValidationError('Payment advance days cannot be negative.')
        names = [self.company_representative, self.company_witness_1, self.company_witness_2, self.renter_witness_1, self.renter_witness_2]
        if not all(name and name.strip() for name in names) or not self.delivery_place or not self.company_email:
            raise ValidationError('Complete delivery place, notices email, company representative and all four witnesses.')
        raw = base64.b64decode(company.cr_contract_pdf)
        if not raw.startswith(b'%PDF'):
            raise ValidationError('The contract template must be a PDF.')
        booking = rental.reservation_id
        snapshot = {'Rental reference': rental.reference, 'Reservation': booking.reference,
                    'Named renter': rental.customer_id.display_name,
                    'Registration': rental.vehicle_id.registration_number, 'Manufacturer': rental.vehicle_id.brand,
                    'Type / Model': rental.vehicle_id.model, 'Colour': rental.vehicle_id.color,
                    'Delivery date (UTC)': str(booking.pickup_datetime), 'Return date (UTC)': str(booking.expected_return_datetime),
                    'Lease period (24-hour days)': booking.number_of_days, 'Delivery place': self.delivery_place,
                    'Permitted base / destination (clause 10.9)': booking.destination_id.name,
                    'Security deposit': booking.deposit_required, 'Daily rental': booking.quoted_daily_rate,
                    'Hire total including tax': booking.amount, 'Currency': rental.currency_id.name,
                    'One-time dirty return cleaning fee': booking.cleaning_fee,
                    'Payment advance deadline, days (clause 6)': self.payment_advance_days,
                    'Company notices email (clause 23.1)': self.company_email,
                    'Company representative': self.company_representative,
                    'Company witness 1': self.company_witness_1, 'Company witness 2': self.company_witness_2,
                    'Renter witness 1': self.renter_witness_1, 'Renter witness 2': self.renter_witness_2}
        self._store({'source_pdf': company.cr_contract_pdf, 'source_filename': company.cr_contract_filename,
                     'template_version': company.cr_contract_version, 'source_hash': hashlib.sha256(raw).hexdigest(),
                     'snapshot': json.dumps(snapshot, ensure_ascii=False), 'state': 'sent',
                     'expires_on': fields.Datetime.now() + timedelta(days=30)})
        names = dict(zip([r for r, label in ROLES], [rental.customer_id.display_name] + names))
        for role, label in ROLES:
            self.env['car.rental.contract.signer']._new_request(self, role, names[role])
        self.message_post(body='Contract issued. Share each private link only with its named signer. No messages were sent automatically.')

    def action_revoke(self):
        require_role(self.env, 'group_rental_manager')
        for contract in self:
            contract._lock()
            if contract.state == 'complete':
                raise ValidationError('A fully signed agreement cannot be revoked here.')
            contract._store({'state': 'cancelled'})
            contract.message_post(body='Contract revoked. All its signing links are disabled; existing signatures are retained.')

    def _prefill(self):
        if self.customer_details:
            return json.loads(self.customer_details)
        c = self.rental_id.customer_id
        return {'full_name': c.display_name, 'identity': c.cin, 'physical_address': c.physical_address,
                'postal_address': c.postal_address, 'phone': c.phone, 'email': c.email, 'licence': c.driving_license}

    def _pdf(self, include_signatures=True):
        self.ensure_one()
        output = io.BytesIO()
        styles = getSampleStyleSheet()
        items = [Paragraph('Digital completion schedule', styles['Title']),
                 Paragraph('This schedule completes the blank particulars in the attached original contract. '
                           'The Third Schedule delivery receipt is completed separately at actual handover.', styles['Normal'])]
        styles['Normal'].fontSize = 9
        styles['Normal'].leading = 12
        width = A4[0] - 80
        def paragraph(value):
            return Paragraph(escape(str('' if value is None or value is False else value)).replace('\n', '<br/>'), styles['Normal'])
        def section(title, pairs, compact=True):
            items.append(Paragraph(title, styles['Heading2']))
            if compact:
                entries = [[Paragraph('<b>%s</b>' % escape(label), styles['Normal']), paragraph(value)] for label, value in pairs]
                cells = [[entries[i], entries[i + 1] if i + 1 < len(entries) else ''] for i in range(0, len(entries), 2)]
            else:
                cells = [[Paragraph('<b>%s</b>' % escape(label), styles['Normal']), paragraph(value)] for label, value in pairs]
            table = Table(cells, colWidths=[width / 2] * 2 if compact else [150, width - 150], hAlign='LEFT')
            table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.HexColor('#f0f5f6'), colors.white]),
                ('LEFTPADDING', (0, 0), (-1, -1), 8), ('RIGHTPADDING', (0, 0), (-1, -1), 8),
                ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4)]))
            items.append(table)
        section('Vehicle and booking', list(json.loads(self.snapshot or '{}').items()))
        section('Customer and next of kin', [(label, self._prefill().get(key)) for key, label in CUSTOMER_FIELDS])
        if include_signatures:
            items.extend([PageBreak(), Paragraph('Signatures', styles['Title']),
                          paragraph('Each signature applies to the same original contract and completed particulars. Times below are UTC.'), Spacer(1, 14)])
            cards = []
            for signer in self.signer_ids:
                card = [Paragraph(escape(dict(ROLES)[signer.role]), styles['Heading3']),
                        paragraph(signer.name), paragraph('Signed: %s' % signer.signed_on if signer.signed_on else 'Awaiting signature'), Spacer(1, 8)]
                if signer.signature:
                    image = PDFImage(io.BytesIO(base64.b64decode(signer.signature)), width=180, height=60, kind='proportional')
                    image.hAlign = 'LEFT'
                    card.append(image)
                else:
                    card.append(Spacer(1, 60))
                cards.append(card)
            for index in range(0, len(cards), 2):
                table = Table([[cards[index], cards[index + 1] if index + 1 < len(cards) else '']], colWidths=[width / 2] * 2)
                table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('BOX', (0, 0), (-1, -1), .5, colors.HexColor('#bacbd0')),
                    ('INNERGRID', (0, 0), (-1, -1), .5, colors.HexColor('#bacbd0')),
                    ('LEFTPADDING', (0, 0), (-1, -1), 12), ('RIGHTPADDING', (0, 0), (-1, -1), 12),
                    ('TOPPADDING', (0, 0), (-1, -1), 8), ('BOTTOMPADDING', (0, 0), (-1, -1), 12)]))
                items.append(KeepTogether([table, Spacer(1, 10)]))
        def digest_lines(value):
            return '\n'.join(value[i:i + 32] for i in range(0, len(value), 32))
        section('Document verification', [('Template', self.template_version), ('Original PDF SHA-256', digest_lines(self.source_hash)),
            ('Signed content SHA-256', digest_lines(self.document_hash) if self.document_hash else 'Customer details not yet submitted')], compact=False)
        def footer(canvas, doc):
            canvas.saveState()
            canvas.setFont('Helvetica', 8)
            canvas.drawString(40, 22, 'Digital completion schedule - %s' % self.rental_id.reference)
            canvas.drawRightString(A4[0] - 40, 22, 'Schedule page %s' % doc.page)
            canvas.restoreState()
        SimpleDocTemplate(output, pagesize=A4, leftMargin=40, rightMargin=40, topMargin=36, bottomMargin=40).build(items, onFirstPage=footer, onLaterPages=footer)
        return merge_pdf([base64.b64decode(self.source_pdf), output.getvalue()])

    def _finish(self):
        if len(self.signer_ids) != 6 or any(not s.signed_on for s in self.signer_ids):
            return
        renter = self.signer_ids.filtered(lambda s: s.role == 'renter')
        self._store({'state': 'complete', 'completed_pdf': base64.b64encode(self._pdf()),
                     'completed_filename': 'Signed agreement - %s.pdf' % self.rental_id.reference})
        rental = self.rental_id
        rental.write({'agreement_signature': renter.signature, 'agreement_signed_by': renter.name,
                      'agreement_terms': 'Original contract: %s\nSHA-256: %s\nSigned digital completion schedule: %s\nAll six signatures are retained in Digital Agreements.' % (self.template_version, self.source_hash, self.document_hash)})
        rental.action_sign_agreement()
        self.message_post(body='Customer, company representative and all four witnesses have signed. Signed PDF retained.')


class Signer(models.Model):
    _name = 'car.rental.contract.signer'
    _description = 'Contract Signature Request'
    contract_id = fields.Many2one('car.rental.contract', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='contract_id.company_id', store=True)
    role = fields.Selection(ROLES, required=True)
    name = fields.Char(required=True)
    token = fields.Char(groups='base.group_user', copy=False)
    link = fields.Char(compute='_compute_link', groups='base.group_user')
    signed_on = fields.Datetime(readonly=True)
    signature = fields.Binary(attachment=True, readonly=True)
    signed_hash = fields.Char(readonly=True)
    _role_unique = models.Constraint('UNIQUE(contract_id,role)', 'Each role must have exactly one signature request.')

    def _compute_link(self):
        base = self.env['ir.config_parameter'].sudo().get_param('web.base.url').rstrip('/')
        for signer in self:
            signer.link = '%s/rental/contract/%s/%s' % (base, signer.id, signer.token)

    @api.model
    def _new_request(self, contract, role, name):
        return super(Signer, self).create({'contract_id': contract.id, 'role': role, 'name': name, 'token': secrets.token_urlsafe(32)})

    @api.model_create_multi
    def create(self, vals_list):
        raise ValidationError('Issue a contract to create its signature requests.')

    def write(self, vals):
        raise ValidationError('Use the private signing link to sign this request.')

    def unlink(self):
        raise ValidationError('Signature requests are retained for the audit trail.')

    def _submit(self, values, signature):
        self.ensure_one()
        contract = self.contract_id
        contract._lock()
        self.invalidate_recordset()
        if self.signed_on or contract.state not in ('sent', 'signing') or contract.expires_on < fields.Datetime.now() or contract.rental_id.status != 'draft':
            raise ValidationError('This signing request is no longer available.')
        try:
            raw = base64.b64decode(signature, validate=True)
            if len(raw) > 500000:
                raise ValueError()
            im = Image.open(io.BytesIO(raw))
            if im.format != 'PNG' or im.width > 2000 or im.height > 1000 or im.width < 50 or im.height < 20:
                raise ValueError()
            im.load()
            # Transparent pixels must not make an empty signature appear non-blank.
            rgba = im.convert('RGBA')
            white = Image.new('RGBA', rgba.size, 'white')
            white.alpha_composite(rgba)
            if white.convert('L').getextrema()[0] > 240:
                raise ValueError()
        except Exception as exc:
            raise ValidationError('Draw a signature before submitting.') from exc
        if self.role == 'renter':
            cleaned = {key: str(values.get(key) or '').strip()[:2000] for key, label in CUSTOMER_FIELDS}
            required = [k for k, label in CUSTOMER_FIELDS if k not in ('email', 'kin_email')]
            if any(not cleaned[k] for k in required):
                raise ValidationError('Complete your identity, addresses, licence, contact, next-of-kin and signing place.')
            content = json.dumps(cleaned, sort_keys=True, ensure_ascii=False)
            digest = hashlib.sha256((contract.source_hash + contract.snapshot + content).encode()).hexdigest()
            contract._store({'customer_details': content, 'document_hash': digest,
                             'submitted_on': fields.Datetime.now(), 'state': 'signing'})
        elif contract.state != 'signing' or not contract.document_hash:
            raise ValidationError('The customer must complete and sign the agreement first.')
        super().write({'signature': signature, 'signed_on': fields.Datetime.now(), 'signed_hash': contract.document_hash})
        contract.message_post(body='%s signed as %s.' % (self.name, dict(ROLES)[self.role]))
        contract._finish()
