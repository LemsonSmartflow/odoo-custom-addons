# Part of Odoo. See LICENSE file for full copyright and licensing details.

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

VEHICLE_RENTAL_STATUSES = [
    ('available', 'Available'),
    ('reserved', 'Reserved'),
    ('rented', 'Rented'),
    ('inspection_pending', 'Returned - Inspection Pending'),
    ('cleaning', 'Cleaning'),
    ('maintenance', 'Maintenance'),
    ('damaged', 'Accident/Damaged'),
    ('decommissioned', 'Decommissioned'),
]

TRACKER_STATUSES = [
    ('none', 'Not Installed'),
    ('working', 'Operational'),
    ('not_working', 'Not Working'),
]


class FleetVehicle(models.Model):
    _inherit = 'fleet.vehicle'

    # Website fields
    website_published = fields.Boolean(string='Published on Website', copy=False, default=False)
    website_sequence = fields.Integer(string='Website Sequence', copy=False)
    website_description = fields.Html(string='Website Description', sanitize=True)
    slug = fields.Char(string='URL Slug', compute='_compute_slug', store=True)
    website_price_ids = fields.One2many(
        'vehicle.website.price', 'vehicle_id', string='Website Pricing')
    image_gallery_ids = fields.One2many(
        'vehicle.image.gallery', 'vehicle_id', string='Photo Gallery')
    website_image_count = fields.Integer(compute='_compute_website_image_count')

    rental_fleet_id = fields.Char(
        string='Fleet ID', copy=False, index=True,
        help='Unique rental fleet identifier, e.g. DEMIO-003.')
    rental_status = fields.Selection(
        selection=VEHICLE_RENTAL_STATUSES, string='Rental Status',
        default='available', tracking=True, required=True, copy=False,
        help='Rental lifecycle: Available > Reserved > Rented > Returned - Inspection Pending '
             '> Cleaning > Available. Exception paths via Maintenance or Accident/Damaged.')
    rental_category_id = fields.Many2one(
        'car.rental.vehicle.category', string='Rental Category', tracking=True)
    current_rental_customer_id = fields.Many2one(
        'res.partner', string='Current Customer', readonly=True, tracking=True, copy=False)
    current_rental_order_id = fields.Many2one(
        'sale.order', string='Current Rental Order', readonly=True, copy=False)
    current_destination_id = fields.Many2one(
        'car.rental.destination', string='Current Destination', readonly=True, copy=False)
    rental_order_count = fields.Integer(compute='_compute_rental_order_count', string='Rental Orders')

    tracker_installed = fields.Boolean(string='Tracker Installed')
    tracker_id = fields.Char(string='Tracker ID')
    tracker_status = fields.Selection(
        selection=TRACKER_STATUSES, string='Tracker Status', default='none', tracking=True)
    insurance_expiry = fields.Date(string='Insurance Expiry', tracking=True)
    road_licence_expiry = fields.Date(string='Road Licence Expiry', tracking=True)
    fitness_expiry = fields.Date(string='Fitness Expiry', tracking=True)
    current_mileage = fields.Float(string='Current Mileage (km)')
    next_service_mileage = fields.Float(
        string='Next Service Mileage (km)',
        help='When the current mileage reaches this value, a maintenance activity is raised.')
    rental_reserved = fields.Boolean(compute='_compute_rental_reserved', string='Has Rental Commitments')

    _rental_fleet_id_uniq = models.Constraint(
        'UNIQUE (rental_fleet_id, company_id)',
        'The rental fleet ID must be unique per company.',
    )

    def _compute_rental_order_count(self):
        group = self.env['sale.order']._read_group(
            [('allocated_vehicle_id', 'in', self.ids)], ['allocated_vehicle_id'], aggregates=['__count'],
        )
        count_by_vehicle = {vehicle.id: count for vehicle, count in group}
        for vehicle in self:
            vehicle.rental_order_count = count_by_vehicle.get(vehicle.id, 0)

    def _compute_rental_reserved(self):
        for vehicle in self:
            vehicle.rental_reserved = vehicle.rental_status not in ('available', 'decommissioned')

    @api.depends('name', 'rental_fleet_id')
    def _compute_slug(self):
        for vehicle in self:
            name = (vehicle.name or '').lower().replace(' ', '-')
            fleet_id = (vehicle.rental_fleet_id or str(vehicle.id)).lower().replace(' ', '-')
            vehicle.slug = '%s-%s' % (name, fleet_id)

    def _compute_website_image_count(self):
        for vehicle in self:
            vehicle.website_image_count = len(vehicle.image_gallery_ids)

    def _check_rental_availability(self):
        for vehicle in self:
            if vehicle.rental_status == 'decommissioned':
                raise UserError(_(
                    'Vehicle "%(vehicle)s" is decommissioned and cannot be rented.',
                    vehicle=vehicle.display_name))
            if vehicle.rental_status != 'available':
                raise UserError(_(
                    'Vehicle "%(vehicle)s" is not available (current status: %(status)s).',
                    vehicle=vehicle.display_name, status=vehicle.rental_status))

    def _check_handover_readiness(self, order):
        """Server-side checks before handing a vehicle to a customer."""
        self.ensure_one()
        if self.rental_status not in ('reserved', 'available'):
            raise UserError(_(
                'Vehicle "%(vehicle)s" cannot be handed over: status is %(status)s.',
                vehicle=self.display_name, status=self.rental_status))
        company = order.company_id
        today = fields.Date.context_today(self)
        compliance = [
            ('insurance_expiry', _('Insurance')),
            ('road_licence_expiry', _('Road Licence')),
            ('fitness_expiry', _('Fitness')),
        ]
        expired = [label for field, label in compliance if self[field] and self[field] < today]
        if expired:
            message = _(
                'Vehicle "%(vehicle)s" has expired %(labels)s. Handover is blocked.',
                vehicle=self.display_name, labels=', '.join(expired))
            if company.rental_compliance_block:
                raise UserError(message)
            self.message_post(body=message)
        if self.tracker_status == 'not_working':
            message = _(
                'Vehicle "%(vehicle)s" has a non-operational tracker.', vehicle=self.display_name)
            if company.rental_tracker_block:
                raise UserError(message)
            self.message_post(body=message)

    def action_set_available(self):
        self.filtered(lambda v: v.rental_status != 'rented').write({
            'rental_status': 'available',
            'current_rental_customer_id': False,
            'current_rental_order_id': False,
            'current_destination_id': False,
        })

    def action_set_cleaning(self):
        self.write({'rental_status': 'cleaning'})

    def action_set_maintenance(self):
        self.write({'rental_status': 'maintenance'})

    def action_set_damaged(self):
        self.write({'rental_status': 'damaged'})

    def action_decommission(self):
        self.filtered(lambda v: v.rental_status != 'rented').write({'rental_status': 'decommissioned'})

    def action_view_rental_orders(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('car_rental_management.action_car_rental_order')
        action['domain'] = [('allocated_vehicle_id', '=', self.id)]
        action['context'] = {
            'default_allocated_vehicle_id': self.id,
            'default_rental_vehicle_category_id': self.rental_category_id.id,
        }
        return action

    def _create_expiry_activity(self, label, expiry_date):
        self.ensure_one()
        summary = _('%(label)s expires on %(date)s', label=label, date=expiry_date)
        existing = self.env['mail.activity'].search_count([
            ('res_model', '=', self._name),
            ('res_id', '=', self.id),
            ('summary', '=', summary),
        ])
        if existing:
            return False
        self.activity_schedule(
            'mail.mail_activity_data_todo',
            date_deadline=expiry_date,
            summary=summary,
            note=_('Compliance document is due to expire. Renew before the rental fleet is impacted.'),
        )
        return True

    @api.model
    def _cron_rental_compliance(self):
        """Create activities 30/60/90 days ahead of insurance / licence / fitness expiry."""
        today = fields.Date.context_today(self)
        compliance_fields = [
            ('insurance_expiry', _('Insurance')),
            ('road_licence_expiry', _('Road Licence')),
            ('fitness_expiry', _('Fitness')),
        ]
        for field, label in compliance_fields:
            domain = [(field, '!=', False), (field, '>=', today), (field, '<=', today + relativedelta(days=90))]
            for vehicle in self.search(domain):
                expiry_date = vehicle[field]
                if (expiry_date - today).days % 30 == 0 or (expiry_date - today).days <= 30:
                    vehicle._create_expiry_activity(label, expiry_date)
        expired_domain = ['|', '|',
                          '&', ('insurance_expiry', '!=', False), ('insurance_expiry', '<', today),
                          '&', ('road_licence_expiry', '!=', False), ('road_licence_expiry', '<', today),
                          '&', ('fitness_expiry', '!=', False), ('fitness_expiry', '<', today),
                          ]
        for vehicle in self.search(expired_domain):
            expired = [
                label for field, label in compliance_fields
                if vehicle[field] and vehicle[field] < today
            ]
            if expired:
                vehicle.message_post(body=_(
                    'Vehicle "%(vehicle)s" has expired %(labels)s. It cannot be handed over until renewed.',
                    vehicle=vehicle.display_name, labels=', '.join(expired)))

    @api.model
    def _cron_rental_maintenance(self):
        """Raise maintenance requests when the mileage or service date threshold is reached."""
        today = fields.Date.context_today(self)
        vehicles = self.search([
            ('rental_status', 'not in', ('decommissioned',)),
            ('next_service_mileage', '>', 0),
        ]).filtered(lambda v: v.current_mileage >= v.next_service_mileage)
        for vehicle in vehicles:
            open_requests = self.env['maintenance.request'].search_count([
                ('rental_vehicle_id', '=', vehicle.id),
                ('stage_id.done', '=', False),
            ])
            if open_requests:
                continue
            self.env['maintenance.request'].create({
                'name': _('Preventive service for %(vehicle)s at %(mileage)s km',
                          vehicle=vehicle.display_name, mileage=vehicle.current_mileage),
                'maintenance_type': 'preventive',
                'request_date': today,
                'rental_vehicle_id': vehicle.id,
                'company_id': vehicle.company_id.id,
            })
            vehicle.message_post(body=_(
                'Maintenance threshold reached (%(mileage)s km). A preventive service request was created.',
                mileage=vehicle.current_mileage))
