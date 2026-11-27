"""Operational job — the field-service side of the demonstration."""
from odoo import api, fields, models


JOB_STATES = [
    ('new', 'New'),
    ('assigned', 'Assigned'),
    ('dispatched', 'Dispatched'),
    ('en_route', 'En Route'),
    ('on_site', 'On Site'),
    ('completed', 'Completed'),
    ('cancelled', 'Cancelled'),
]


class KemOperationalJob(models.Model):
    _name = 'kem.operational.job'
    _description = 'Operational Job'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    reference = fields.Char(
        'Reference', required=True, readonly=True, copy=False,
        default=lambda self: self.env['ir.sequence'].next_by_code('kem.operational.job') or 'NEW',
    )
    name = fields.Char('Job Name', required=True, tracking=True)
    company_id = fields.Many2one('res.company', 'Company', default=lambda self: self.env.company, required=True)
    job_type = fields.Selection([
        ('emergency', 'Emergency response'),
        ('event', 'Event coverage'),
        ('transport', 'Transport'),
        ('support', 'Logistics support'),
    ], 'Job Type', default='event')
    partner_id = fields.Many2one('res.partner', 'Customer', index=True)
    booking_id = fields.Many2one('kem.event.booking', 'Related Booking', ondelete='set null')
    project_id = fields.Many2one('project.project', 'Project', related='booking_id.project_id', readonly=True, store=False)
    team_ids = fields.Many2many('hr.employee', 'kem_job_employee_rel', 'job_id', 'employee_id', string='Assigned Team')
    vehicle_ids = fields.Many2many('fleet.vehicle', 'kem_job_vehicle_rel', 'job_id', 'vehicle_id', string='Allocated Vehicles')
    state = fields.Selection(JOB_STATES, 'Job Status', default='new', tracking=True)
    opened = fields.Datetime('Opened', default=fields.Datetime.now)
    closed = fields.Datetime('Closed')
    notes = fields.Text('Completion Notes')
    documents = fields.Text('Supporting Documentation')

    @api.model
    def _job_order(self):
        return [value for value, _label in JOB_STATES]

    def action_next(self):
        order = self._job_order()
        for job in self:
            index = order.index(job.state)
            if index < len(order) - 2:
                job.state = order[index + 1]
                if job.state == 'completed' and not job.closed:
                    job.closed = fields.Datetime.now()
        return True

    def action_set_state(self):
        """Used by form buttons passing the target state via context."""
        target = self.env.context.get('kem_target_state')
        if target in dict(JOB_STATES):
            for job in self:
                job.state = target
                if target == 'completed' and not job.closed:
                    job.closed = fields.Datetime.now()
        return True

    def action_complete(self):
        for job in self:
            job.state = 'completed'
            job.closed = fields.Datetime.now()
        return True

    def _enterprise_create_fsm_task(self):
        """Hook overridden by the Enterprise Field Service bridge."""
        return True

    def action_view_booking(self):
        self.ensure_one()
        if not self.booking_id:
            return {'type': 'ir.actions.act_window_close'}
        return {
            'type': 'ir.actions.act_window',
            'name': self.booking_id.name,
            'res_model': 'kem.event.booking',
            'res_id': self.booking_id.id,
            'view_mode': 'form',
        }
