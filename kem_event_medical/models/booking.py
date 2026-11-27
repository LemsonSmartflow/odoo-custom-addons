"""Event medical booking.

The booking is the hub of the demonstration: it connects the CRM opportunity,
the sales quotation, the assigned crew, fleet vehicles, the project, the
operational job and the supporting documents. Enterprise integrations are
reached through the `_enterprise_*` hooks, which the bridge addon overrides.
"""
from odoo import api, fields, models


BOOKING_STATES = [
    ('enquiry', 'Enquiry'),
    ('assessment', 'Assessment'),
    ('quotation', 'Quotation'),
    ('awaiting', 'Awaiting Confirmation'),
    ('confirmed', 'Confirmed'),
    ('planning', 'Planning'),
    ('ready', 'Ready for Deployment'),
    ('in_progress', 'In Progress'),
    ('completed', 'Completed'),
    ('cancelled', 'Cancelled'),
]


class KemEventBooking(models.Model):
    _name = 'kem.event.booking'
    _description = 'Event Medical Booking'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'start_date desc, id desc'

    reference = fields.Char(
        'Reference', required=True, readonly=True, copy=False,
        default=lambda self: self.env['ir.sequence'].next_by_code('kem.event.booking') or 'NEW',
    )
    name = fields.Char('Event Name', required=True, tracking=True)
    company_id = fields.Many2one('res.company', 'Company', default=lambda self: self.env.company, required=True)
    partner_id = fields.Many2one('res.partner', 'Customer', tracking=True, index=True)
    opportunity_id = fields.Many2one('crm.lead', 'CRM Opportunity', ondelete='set null')
    sale_order_id = fields.Many2one('sale.order', 'Quotation / Sales Order', ondelete='set null')
    project_id = fields.Many2one('project.project', 'Project', ondelete='set null')

    event_type = fields.Selection([
        ('sporting', 'Sporting event'),
        ('corporate', 'Corporate event'),
        ('community', 'Community event'),
        ('private', 'Private event'),
        ('construction', 'Construction project'),
        ('conference', 'Conference / exhibition'),
        ('other', 'Other'),
    ], 'Event Type', default='other')
    location = fields.Char('Event Location')
    start_date = fields.Date('Event Start Date', tracking=True)
    end_date = fields.Date('Event End Date')
    service_start = fields.Char('Service Start Time', size=5)
    service_end = fields.Char('Service End Time', size=5)
    attendance = fields.Integer('Estimated Attendance')
    organiser = fields.Char('Event Organiser Contact')
    organiser_phone = fields.Char('Organiser Phone')
    requirement = fields.Text('Service Requirements')
    personnel_required = fields.Integer('Personnel Required', default=0)
    vehicle_required = fields.Char('Vehicle Requirements')
    equipment_required = fields.Text('Equipment Requirements')

    state = fields.Selection(BOOKING_STATES, 'Booking Status', default='enquiry', tracking=True)
    team_ids = fields.Many2many('hr.employee', 'kem_booking_employee_rel', 'booking_id', 'employee_id', string='Assigned Team')
    vehicle_ids = fields.Many2many('fleet.vehicle', 'kem_booking_vehicle_rel', 'booking_id', 'vehicle_id', string='Allocated Vehicles')
    notes = fields.Text('Operational Notes')
    completion_notes = fields.Text('Completion Notes')

    job_ids = fields.One2many('kem.operational.job', 'booking_id', string='Operational Jobs')
    document_ids = fields.One2many('kem.document.record', 'booking_id', string='Document Records')
    crew_count = fields.Integer('Assigned Crew', compute='_compute_crew_count', store=False)
    color = fields.Integer('Colour')

    @api.depends('team_ids')
    def _compute_crew_count(self):
        for booking in self:
            booking.crew_count = len(booking.team_ids)

    @api.model
    def _booking_order(self):
        return [value for value, _label in BOOKING_STATES]

    def action_next(self):
        order = self._booking_order()
        for booking in self:
            index = order.index(booking.state)
            if index < len(order) - 2:  # never step into Cancelled automatically
                booking.state = order[index + 1]
        return True

    def _won_stage(self):
        return self.env['crm.stage'].sudo().search([('is_won', '=', True)], limit=1)

    def action_confirm(self):
        """Step 4 of the demonstration: quotation accepted, booking confirmed."""
        for booking in self:
            booking.state = 'confirmed'
            if booking.opportunity_id and not booking.opportunity_id.stage_id.is_won:
                won = booking._won_stage()
                if won:
                    booking.opportunity_id.stage_id = won
            if not booking.project_id and booking.name:
                booking.project_id = self.env['project.project'].create({
                    'name': booking.name,
                    'partner_id': booking.partner_id.id,
                    'company_id': booking.company_id.id,
                })
            booking.message_post(body='Booking confirmed; project and cross-app links prepared.')
            booking._enterprise_on_confirm()
        return True

    def action_plan(self):
        for booking in self:
            booking.state = 'planning'
        return True

    def action_ready(self):
        """Step 5: crew and vehicles assigned; planning records synchronised."""
        for booking in self:
            booking.state = 'ready'
            booking._ensure_job()
            booking._enterprise_create_planning_slots()
            booking.message_post(body='Marked ready for deployment with %s crew member(s).' % booking.crew_count)
        return True

    def action_deploy(self):
        for booking in self:
            booking.state = 'in_progress'
            for job in booking.job_ids.filtered(lambda j: j.state in ('new', 'assigned')):
                job.state = 'dispatched'
        return True

    def action_complete(self):
        """Step 8: close the booking and its job, then publish records."""
        for booking in self:
            booking.state = 'completed'
            for job in booking.job_ids.filtered(lambda j: j.state != 'completed'):
                job.state = 'completed'
                job.closed = fields.Datetime.now()
            booking._enterprise_on_complete()
            booking.message_post(body='Event completed and service records published.')
        return True

    def _ensure_job(self):
        self.ensure_one()
        if self.job_ids:
            return self.job_ids[0]
        job = self.env['kem.operational.job'].create({
            'name': '%s — medical standby' % self.name,
            'job_type': 'event',
            'booking_id': self.id,
            'partner_id': self.partner_id.id,
            'company_id': self.company_id.id,
            'team_ids': [(6, 0, self.team_ids.ids)],
            'vehicle_ids': [(6, 0, self.vehicle_ids.ids)],
            'state': 'assigned',
            'opened': fields.Datetime.now(),
            'notes': self.notes,
        })
        job._enterprise_create_fsm_task()
        return job

    def action_create_job(self):
        for booking in self:
            booking._ensure_job()
        return True

    def action_view_jobs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Operational Jobs — %s' % self.reference,
            'res_model': 'kem.operational.job',
            'view_mode': 'list,form',
            'domain': [('booking_id', '=', self.id)],
            'context': {'default_booking_id': self.id, 'default_partner_id': self.partner_id.id},
        }

    def action_view_documents(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Documents — %s' % self.reference,
            'res_model': 'kem.document.record',
            'view_mode': 'list,form',
            'domain': [('booking_id', '=', self.id)],
            'context': {'default_booking_id': self.id, 'default_partner_id': self.partner_id.id},
        }

    # ------------------------------------------------------------------
    # Integration hooks. The Enterprise bridge overrides these methods.
    # Keeping them here means the core addon never references Enterprise models.
    # ------------------------------------------------------------------
    def _enterprise_on_confirm(self):
        return True

    def _enterprise_create_planning_slots(self):
        return True

    def _enterprise_on_complete(self):
        return True
