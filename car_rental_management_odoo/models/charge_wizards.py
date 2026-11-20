from odoo import api, fields, models
from odoo.exceptions import ValidationError

from .pricing import require_role
from .workflow import window


class QuoteChargeWizard(models.TransientModel):
    _name = 'car.rental.quote.charge.wizard'
    _description = 'Booking Delivery Charge'

    journey_id = fields.Many2one('car.rental.journey', required=True, readonly=True)
    reservation_id = fields.Many2one(related='journey_id.reservation_id', readonly=True)
    company_id = fields.Many2one(related='journey_id.company_id', readonly=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    delivery_service = fields.Boolean(related='journey_id.booking_delivery_service')
    delivery_address = fields.Char(string='Delivery Address')
    delivery_fee = fields.Monetary(string='Delivery Charge', currency_field='currency_id')

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        journey = self.env['car.rental.journey'].browse(
            self.env.context.get('default_journey_id')).exists()
        if not journey:
            return values
        company = journey.company_id
        values.update({
            'journey_id': journey.id,
            'delivery_address': journey.booking_delivery_address,
            'delivery_fee': journey.booking_delivery_fee or (
                company.cr_delivery_product_id.list_price
                if company.cr_delivery_product_id else 0
            ),
        })
        return values

    def action_confirm(self):
        self.ensure_one()
        journey = self.journey_id
        if journey.step != 'booking' or (
            journey.reservation_id
            and (journey.reservation_id.status != 'draft' or journey.reservation_id.rental_ids)
        ):
            raise ValidationError('Customer delivery can only be added before confirming the booking quote.')
        if self.delivery_service and not self.company_id.cr_delivery_product_id:
            raise ValidationError('Configure the customer delivery service product in Car Rental Settings.')
        if self.delivery_service and (not self.delivery_address or self.delivery_fee <= 0):
            raise ValidationError('Customer delivery requires an address and a positive charge.')
        journey.write({
            'booking_delivery_service': self.delivery_service,
            'booking_delivery_address': self.delivery_address if self.delivery_service else False,
            'booking_delivery_fee': self.delivery_fee if self.delivery_service else 0,
        })
        journey._ensure_draft_reservation()
        journey._advance_to('quote')
        return journey.action_open()


class ReturnChargeWizard(models.TransientModel):
    _name = 'car.rental.return.charge.wizard'
    _description = 'Confirm Vehicle Return Charges'

    rental_id = fields.Many2one('car.rental.rental', required=True, readonly=True)
    company_id = fields.Many2one(related='rental_id.company_id', readonly=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    late_days = fields.Integer(readonly=True)
    late_unit_price = fields.Monetary(
        string='Charge per Late Day', currency_field='currency_id')
    late_charge = fields.Monetary(
        compute='_compute_late_charge', string='Late-return Total',
        currency_field='currency_id')
    cleaning_required = fields.Boolean(string='Dirty-return Cleaning Applies', readonly=True)
    cleaning_charge = fields.Monetary(string='Cleaning Charge', currency_field='currency_id')
    collection_service = fields.Boolean(related='rental_id.return_collection_service', readonly=False)
    collection_address = fields.Char(string='Vehicle Collection Address')
    collection_fee = fields.Monetary(string='Vehicle Collection Charge', currency_field='currency_id')

    @api.depends('late_days', 'late_unit_price', 'currency_id')
    def _compute_late_charge(self):
        for wizard in self:
            wizard.late_charge = wizard.currency_id.round(
                wizard.late_days * wizard.late_unit_price)

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        rental = self.env['car.rental.rental'].browse(
            self.env.context.get('default_rental_id')).exists()
        if not rental:
            return values
        details = rental._return_charge_details()
        values.update({
            'rental_id': rental.id,
            'late_days': details['late_days'],
            'late_unit_price': (
                rental.company_id.cr_late_product_id.list_price
                if rental.company_id.cr_late_product_id else 0
            ),
            'cleaning_required': details['cleaning_required'],
            'cleaning_charge': (
                rental.company_id.cr_cleaning_product_id.list_price
                if rental.company_id.cr_cleaning_product_id else 0
            ),
            'collection_address': rental.return_collection_address,
            'collection_fee': rental.return_collection_fee or (
                rental.company_id.cr_collection_product_id.list_price
                if rental.company_id.cr_collection_product_id else 0
            ),
        })
        return values

    def action_confirm(self):
        self.ensure_one()
        rental = self.rental_id
        if rental.status != 'ongoing' or not rental.return_inspection_done:
            raise ValidationError('The return inspection is no longer ready for charge confirmation.')
        details = rental._return_charge_details()
        if details['late_days'] != self.late_days or details['cleaning_required'] != self.cleaning_required:
            raise ValidationError('The return inspection or late-return period changed. Reopen the charge confirmation.')
        late_unit_price = self.late_unit_price if details['late_days'] else 0
        late_charge = self.currency_id.round(
            details['late_days'] * late_unit_price)
        cleaning_charge = self.cleaning_charge if details['cleaning_required'] else 0
        if details['late_days'] and (
            not rental.company_id.cr_late_product_id or late_unit_price <= 0
        ):
            raise ValidationError('Enter a positive late-return charge and configure its service product.')
        if details['cleaning_required'] and (
            not rental.company_id.cr_cleaning_product_id or cleaning_charge <= 0
        ):
            raise ValidationError('Enter a positive dirty-return charge and configure its service product.')
        if self.collection_service and (
            not rental.company_id.cr_collection_product_id
            or not self.collection_address or self.collection_fee <= 0
        ):
            raise ValidationError(
                'Vehicle collection requires an address, a positive charge and a configured service product.')
        rental._workflow_write({
            'late_days': details['late_days'],
            'late_unit_price': late_unit_price,
            'late_charge': late_charge,
            'cleaning_charge': cleaning_charge,
            'return_collection_address': self.collection_address if self.collection_service else False,
            'return_collection_fee': self.collection_fee if self.collection_service else 0,
            'return_charges_confirmed': True,
        })
        journey = self.env['car.rental.journey'].sudo().search(
            [('reservation_id', '=', rental.reservation_id.id)], limit=1)
        if journey and journey.step == 'return':
            return journey.action_continue()
        rental.action_return_vehicle()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Rental',
            'res_model': 'car.rental.rental',
            'view_mode': 'form',
            'res_id': rental.id,
        }


class DamageApprovalWizard(models.TransientModel):
    """Approve a return damage without leaving the guided booking journey."""
    _name = 'car.rental.damage.approval.wizard'
    _description = 'Approve Damage Assessment'

    journey_id = fields.Many2one('car.rental.journey', readonly=True)
    damage_id = fields.Many2one('car.rental.damage.case', readonly=True)
    company_id = fields.Many2one(related='damage_id.company_id', readonly=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    name = fields.Char(related='damage_id.name', readonly=True)
    cost = fields.Monetary(
        string='Assessed Charge',
        currency_field='currency_id',
        help='Enter the amount to charge the customer for this damage.')
    repair_notes = fields.Text(
        string='Assessment / Repair Notes',
        help='Describe the damage and the intended repair before approving.')
    severity = fields.Selection([
        ('minor', 'Minor / cosmetic'),
        ('moderate', 'Moderate / repair needed'),
        ('major', 'Major / safety issue'),
    ], string='Damage Severity', default='minor', required=True)

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        journey = self.env['car.rental.journey'].browse(
            self.env.context.get('default_journey_id')).exists()
        damage = journey.rental_id.damage_ids.filtered(
            lambda case: case.state == 'draft')[:1] if journey else self.env['car.rental.damage.case']
        if not damage:
            damage = self.env['car.rental.damage.case'].browse(
                self.env.context.get('default_damage_id')).exists()
        if damage:
            values.update({
                'journey_id': journey.id,
                'damage_id': damage.id,
                'cost': damage.cost,
                'repair_notes': damage.repair_notes,
                'severity': damage.severity,
            })
        return values

    def action_open_damage(self):
        """Open the authoritative Damage Assessment record in its own app."""
        self.ensure_one()
        return window('Damage Assessment', 'car.rental.damage.case', res_id=self.damage_id.id)

    def action_approve(self):
        self.ensure_one()
        require_role(self.env, 'group_rental_manager')
        if self.currency_id.compare_amounts(self.cost, 0) < 0:
            raise ValidationError('The assessed damage charge cannot be negative.')
        if not self.repair_notes:
            raise ValidationError('Record the damage assessment notes before approving.')
        self.damage_id.write({
            'cost': self.cost,
            'repair_notes': self.repair_notes,
            'severity': self.severity,
        })
        self.damage_id.action_approve()
        journey = self.journey_id
        return journey.action_open() if journey else {'type': 'ir.actions.act_window_close'}
