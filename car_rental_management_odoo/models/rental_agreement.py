"""Reusable rental agreement templates and issued agreements.

The master agreement lives on ``rental.agreement.template``.  Issued agreements
are snapshots: editing a template can never rewrite an agreement that was
already generated or signed.
"""
import base64
import hashlib
import json
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import file_open

from .digital_contract import (
    CHECKBOX_ACCEPTANCE_TEXT, CUSTOMER_FIELDS, ROLES,
)


# Fixed token registry.  Only these keys can be mapped by a template, so no
# arbitrary Python is ever evaluated from template configuration.
AGREEMENT_FIELD_TOKENS = [
    ('renter_name', 'Renter full legal name', 'customer'),
    ('identity_number', 'Omang / National Identity number', 'customer'),
    ('passport_number', 'Passport number', 'customer'),
    ('phone', 'Mobile number', 'customer'),
    ('email', 'Email address', 'customer'),
    ('physical_address', 'Physical address', 'customer'),
    ('postal_address', 'Postal address', 'customer'),
    ('next_of_kin', "Next of kin's full name", 'customer'),
    ('relationship', "Next of kin's relationship", 'customer'),
    ('kin_phone', "Next of kin's mobile number", 'customer'),
    ('kin_email', "Next of kin's email address", 'customer'),
    ('vehicle_registration', 'Vehicle registration number', 'vehicle'),
    ('vehicle_manufacturer', 'Vehicle manufacturer', 'vehicle'),
    ('vehicle_model', 'Vehicle model', 'vehicle'),
    ('vehicle_colour', 'Vehicle colour', 'vehicle'),
    ('delivery_date', 'Delivery date', 'rental'),
    ('lease_period', 'Lease period (days)', 'rental'),
    ('delivery_place', 'Delivery location', 'rental'),
    ('security_deposit', 'Security deposit', 'rental'),
    ('daily_rental', 'Daily rental amount', 'rental'),
    ('agreement_date', 'Agreement date', 'rental'),
    ('operating_location', 'Agreed operating location', 'rental'),
    ('company_representative', 'Company representative', 'signing'),
    ('company_designation', "Representative's designation", 'signing'),
    ('company_email', 'Company notices email', 'signing'),
    ('company_signature', 'Company signature', 'signing'),
    ('renter_signature', "Renter's signature", 'signing'),
    ('company_witness_1', 'Company witness 1', 'signing'),
    ('company_witness_2', 'Company witness 2', 'signing'),
    ('renter_witness_1', 'Renter witness 1', 'signing'),
    ('renter_witness_2', 'Renter witness 2', 'signing'),
    ('execution_place', 'Agreement execution place', 'signing'),
    ('execution_date', 'Agreement execution date', 'signing'),
]
AGREEMENT_FIELD_SELECTION = [(key, label) for key, label, _section in AGREEMENT_FIELD_TOKENS]
FIELD_SECTIONS = [
    ('customer', 'Customer'), ('vehicle', 'Vehicle'),
    ('rental', 'Rental'), ('signing', 'Signing'),
]


class RentalAgreementTemplateField(models.Model):
    _name = 'rental.agreement.template.field'
    _description = 'Rental Agreement Template Field'
    _order = 'sequence, id'

    template_id = fields.Many2one(
        'rental.agreement.template', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    key = fields.Selection(AGREEMENT_FIELD_SELECTION, required=True)
    label = fields.Char(required=True)
    section = fields.Selection(FIELD_SECTIONS, required=True, default='customer')
    required = fields.Boolean(default=False)
    help = fields.Char()

    _key_unique = models.Constraint(
        'UNIQUE(template_id, key)', 'A field can only be mapped once per template.')


class RentalAgreementTemplate(models.Model):
    _name = 'rental.agreement.template'
    _description = 'Rental Agreement Template'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _check_company_auto = True
    _order = 'sequence, id'

    name = fields.Char(required=True, tracking=True)
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)
    version = fields.Char(required=True, default='1.0', tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'), ('active', 'Active'), ('archived', 'Archived'),
    ], default='draft', required=True, tracking=True)
    is_default = fields.Boolean(string='Default Template', tracking=True)
    master_pdf = fields.Binary(
        string='Master Agreement PDF', attachment=True,
        groups='car_rental_management_odoo.group_rental_manager')
    master_filename = fields.Char(default='City Delights Contract.pdf')
    master_hash = fields.Char(
        compute='_compute_master_hash', string='Master PDF SHA-256', store=True)
    field_ids = fields.One2many(
        'rental.agreement.template.field', 'template_id', string='Dynamic Fields',
        groups='car_rental_management_odoo.group_rental_manager')
    completion_text = fields.Text(
        string='Completion Schedule Introduction',
        default='The following particulars complete the blanks in the original agreement. '
                'All other terms, conditions and schedules remain unchanged.')
    acceptance_text = fields.Text(
        string='Electronic Acceptance Wording', default=CHECKBOX_ACCEPTANCE_TEXT)
    require_company_representative = fields.Boolean(default=False)
    require_company_witness_1 = fields.Boolean(default=False)
    require_company_witness_2 = fields.Boolean(default=False)
    require_renter_witness_1 = fields.Boolean(default=False)
    require_renter_witness_2 = fields.Boolean(default=False)
    valid_from = fields.Date()
    valid_to = fields.Date()
    notes = fields.Text()

    @api.constrains('is_default', 'company_id', 'state')
    def _check_single_default(self):
        for template in self.filtered(lambda t: t.is_default and t.state == 'active'):
            others = self.search([
                ('company_id', '=', template.company_id.id),
                ('is_default', '=', True), ('state', '=', 'active'),
                ('id', '!=', template.id),
            ], limit=1)
            if others:
                raise ValidationError(_('Only one active default template is allowed per company.'))

    @api.depends('master_pdf')
    def _compute_master_hash(self):
        for template in self:
            template.master_hash = hashlib.sha256(
                base64.b64decode(template.master_pdf or b'')).hexdigest()

    @api.constrains('master_pdf', 'state')
    def _check_master_pdf(self):
        for template in self.filtered(lambda t: t.state == 'active'):
            if not template.master_pdf:
                raise ValidationError(_('An active template must have a master PDF.'))
            if not base64.b64decode(template.master_pdf)[:4] == b'%PDF':
                raise ValidationError(_('The master document must be a PDF file.'))

    @api.constrains('valid_from', 'valid_to')
    def _check_validity(self):
        for template in self:
            if template.valid_from and template.valid_to and template.valid_from > template.valid_to:
                raise ValidationError(_('The validity end date must follow the start date.'))

    def action_activate(self):
        for template in self:
            if not template.master_pdf:
                raise ValidationError(_('Upload the master agreement before activating.'))
            template.state = 'active'
        return True

    def action_archive(self):
        self.write({'state': 'archived', 'is_default': False})
        return True

    def action_new_version(self):
        self.ensure_one()
        new_version = self.copy({
            'name': self.name,
            'version': '%s-rev' % self.version,
            'state': 'draft',
            'is_default': False,
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'view_mode': 'form',
            'res_id': new_version.id,
            'target': 'current',
        }

    def action_load_city_contract(self):
        """Load the supplied City Delights master agreement as this template."""
        self.ensure_one()
        with file_open(
            'car_rental_management_odoo/data/city_delights_contract.pdf', 'rb'
        ) as source:
            self.master_pdf = base64.b64encode(source.read())
        self.master_filename = 'City Delights Contract.pdf'
        if not self.name:
            self.name = 'City Delights Standard Rental Agreement'
        if not self.version:
            self.version = 'City Delights supplied contract - October 2026'
        return True

    def _field_config(self):
        self.ensure_one()
        return {
            'fields': [
                {'key': line.key, 'label': line.label, 'section': line.section,
                 'required': line.required}
                for line in self.field_ids
            ],
            'completion_text': self.completion_text,
            'acceptance_text': self.acceptance_text,
            'signers': {
                key: bool(self[key])
                for key in ('require_company_representative',
                            'require_company_witness_1', 'require_company_witness_2',
                            'require_renter_witness_1', 'require_renter_witness_2')
            },
        }

    def _resolve_value(self, key, rental, journey=None):
        """Resolve a mapped token from authoritative Odoo records only."""
        self.ensure_one()
        partner = rental.partner_id
        vehicle = rental.vehicle_id
        reservation = rental.reservation_id
        company = rental.company_id
        today = fields.Date.context_today(self)
        mapping = {
            'renter_name': partner.display_name,
            'identity_number': partner.rental_identity_number,
            'passport_number': partner.rental_passport_number,
            'phone': partner.phone,
            'email': partner.email,
            'physical_address': partner.street,
            'postal_address': partner.rental_postal_address,
            'next_of_kin': partner.rental_next_of_kin_name,
            'relationship': partner.rental_next_of_kin_relationship,
            'kin_phone': partner.rental_next_of_kin_phone,
            'kin_email': partner.rental_next_of_kin_email,
            'vehicle_registration': vehicle.license_plate,
            'vehicle_manufacturer': vehicle.model_id.brand_id.name,
            'vehicle_model': vehicle.model_id.name,
            'vehicle_colour': vehicle.color,
            'delivery_date': reservation.pickup_datetime,
            'lease_period': reservation.number_of_days,
            'delivery_place': (journey.agreement_delivery_place if journey else False)
                              or reservation.destination_id.name,
            'security_deposit': reservation.deposit_required,
            'daily_rental': reservation.quoted_daily_rate,
            'agreement_date': fields.Datetime.now(),
            'operating_location': reservation.destination_id.name,
            'company_representative': (journey.agreement_company_representative
                                       if journey else False),
            'company_designation': 'Director',
            'company_email': (journey.agreement_company_email if journey else False)
                             or company.email,
            'company_signature': '',
            'renter_signature': '',
            'company_witness_1': journey.agreement_company_witness_1 if journey else False,
            'company_witness_2': journey.agreement_company_witness_2 if journey else False,
            'renter_witness_1': journey.agreement_renter_witness_1 if journey else False,
            'renter_witness_2': journey.agreement_renter_witness_2 if journey else False,
            'execution_place': (journey.agreement_delivery_place if journey else False)
                               or reservation.destination_id.name,
            'execution_date': fields.Date.context_today(self),
        }
        return mapping.get(key)

    def _prepare_values(self, rental, journey=None):
        """Resolve every mapped token into a frozen JSON snapshot."""
        self.ensure_one()
        values = {}
        for line in self.field_ids:
            values[line.key] = self._resolve_value(line.key, rental, journey)
        return values

    def _check_required_values(self, values):
        self.ensure_one()
        missing = [
            line.label for line in self.field_ids
            if line.required and not values.get(line.key)
        ]
        if missing:
            raise ValidationError(_(
                'Complete the following agreement fields before generating: %s'
            ) % ', '.join(missing))

    @api.model
    def _default_for_company(self, company):
        return self.search([
            ('company_id', '=', company.id), ('state', '=', 'active'),
            ('is_default', '=', True),
        ], limit=1) or self.search([
            ('company_id', '=', company.id), ('state', '=', 'active'),
        ], limit=1)


class RentalAgreement(models.Model):
    _name = 'rental.agreement'
    _description = 'Rental Agreement'
    _inherits = {'car.rental.contract': 'contract_id'}
    _check_company_auto = True

    contract_id = fields.Many2one(
        'car.rental.contract', required=True, readonly=True, ondelete='cascade')
    template_id = fields.Many2one(
        'rental.agreement.template', string='Agreement Template', readonly=True,
        check_company=True)
    template_version_snapshot = fields.Char(readonly=True)
    template_master_hash = fields.Char(readonly=True)
    template_config_snapshot = fields.Text(readonly=True)
    values_snapshot = fields.Text(readonly=True)
    is_legacy = fields.Boolean(readonly=True, default=False)
    rental_id = fields.Many2one('car.rental.rental', related='contract_id.rental_id', store=True)
    company_id = fields.Many2one('res.company', related='contract_id.company_id', store=True)
    contract_state = fields.Selection(related='contract_id.state', store=True, readonly=True)
    agreement_status = fields.Selection([
        ('draft', 'Draft'),
        ('generated', 'Generated'),
        ('sent', 'Sent for Signature'),
        ('signing', 'Partially Signed'),
        ('signed', 'Signed'),
        ('cancelled', 'Cancelled'),
    ], compute='_compute_agreement_status', string='Status')

    @api.depends('contract_id.state')
    def _compute_agreement_status(self):
        mapping = {
            'draft': 'draft', 'sent': 'sent', 'signing': 'signing',
            'complete': 'signed', 'cancelled': 'cancelled',
        }
        for agreement in self:
            agreement.agreement_status = mapping.get(agreement.contract_id.state, 'draft')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('contract_id'):
                rental_id = vals.get('rental_id')
                if not rental_id:
                    raise ValidationError(_(
                        'Select a rental before saving an agreement. Use New Agreement '
                        'to create one from a template, customer and vehicle.'))
                contract = self.env['car.rental.contract'].create({
                    'rental_id': rental_id,
                    'delivery_place': vals.get('delivery_place'),
                    'company_email': vals.get('company_email'),
                    'payment_advance_days': vals.get('payment_advance_days', 0),
                })
                vals['contract_id'] = contract.id
        return super().create(vals_list)

    def _snapshot_template(self, template, values):
        self.ensure_one()
        self._store_agreement({
            'template_id': template.id,
            'template_version_snapshot': template.version,
            'template_master_hash': template.master_hash,
            'template_config_snapshot': json.dumps(template._field_config(), sort_keys=True),
            'values_snapshot': json.dumps(values, sort_keys=True, ensure_ascii=False, default=str),
        })

    def _store_agreement(self, vals):
        """Write protected snapshot fields through a privileged bypass."""
        super(RentalAgreement, self).write(vals)

    def write(self, vals):
        protected = {
            'template_id', 'template_version_snapshot', 'template_master_hash',
            'template_config_snapshot', 'values_snapshot', 'is_legacy', 'contract_id',
        }
        if protected.intersection(vals):
            raise ValidationError(_('Agreement snapshots cannot be changed.'))
        return super().write(vals)

    def _logo_data_uri(self):
        try:
            with file_open(
                'car_rental_management_odoo/static/src/img/city_delights_logo.png', 'rb'
            ) as source:
                return 'data:image/png;base64,%s' % base64.b64encode(source.read()).decode()
        except Exception:
            return ''

    def agreement_value(self, key, default=''):
        """Return a snapshotted value for use in QWeb (safe for missing keys)."""
        self.ensure_one()
        values = json.loads(self.values_snapshot or '{}')
        value = values.get(key, default)
        return '' if value is None or value is False else value

    def action_generate(self):
        """Prepare the issued packet from the snapshotted template and values."""
        self.ensure_one()
        contract = self.contract_id
        if contract.state != 'draft':
            raise ValidationError(_('Only a draft agreement can be generated.'))
        template = self.template_id
        values = json.loads(self.values_snapshot or '{}')
        config = json.loads(self.template_config_snapshot or '{}')
        template._check_required_values(values)
        if not contract.company_email:
            contract._store({'company_email': values.get('company_email') or
                             self.rental_id.company_id.email or 'office@example.com'})
        # Reuse the existing, locked issuance logic.  action_prepare reads the
        # template master/hash/snapshot from this facade and creates signers.
        contract.action_prepare()
        return True

    def action_preview(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': '/rental/agreement/%s/pdf/review' % self.id,
            'target': 'new',
        }

    def action_download_pdf(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': '/rental/agreement/%s/pdf/completed' % self.id,
            'target': 'self',
        }

    def action_view_signed(self):
        return self.action_download_pdf()

    def action_cancel_agreement(self):
        self.ensure_one()
        self.contract_id.action_revoke()
        return True

    # Delegated actions from car.rental.contract (fields delegate, methods do not)
    def action_send_via_odoo_sign(self):
        self.ensure_one()
        return self.contract_id.action_send_via_odoo_sign()

    def action_sync_odoo_sign(self):
        self.ensure_one()
        return self.contract_id.action_sync_odoo_sign()
