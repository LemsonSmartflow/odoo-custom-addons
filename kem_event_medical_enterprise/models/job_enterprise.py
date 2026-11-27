"""Field Service synchronisation for operational jobs."""
from odoo import fields, models


class KemOperationalJob(models.Model):
    _inherit = 'kem.operational.job'

    fieldservice_task_id = fields.Many2one('project.task', 'Field Service Task', readonly=True, copy=False)
    planning_slot_ids = fields.One2many('planning.slot', 'kem_job_id', string='Planning Slots')
    documents_document_ids = fields.One2many('documents.document', 'kem_job_id', string='Documents App Files')

    def _enterprise_create_fsm_task(self):
        if not self.env['ir.module.module'].sudo().search_count([
            ('name', '=', 'fieldservice'), ('state', '=', 'installed')
        ]):
            return True
        Task = self.env['project.task'].sudo()
        for job in self:
            if job.fieldservice_task_id:
                continue
            project = job.project_id
            if not project and job.name:
                project = self.env['project.project'].sudo().create({
                    'name': job.name,
                    'partner_id': job.partner_id.id,
                    'company_id': job.company_id.id,
                })
            vals = {
                'name': job.name,
                'project_id': project.id,
                'partner_id': job.partner_id.id,
                'company_id': job.company_id.id,
                'kem_job_id': job.id,
                'kem_booking_id': job.booking_id.id,
                'description': job.notes,
            }
            fields_map = Task._fields
            if 'is_fsm' in fields_map:
                vals['is_fsm'] = True
            if 'fsm_location_id' in fields_map and job.partner_id:
                vals['fsm_location_id'] = job.partner_id.id
            task = Task.create(vals)
            job.fieldservice_task_id = task
            job.message_post(body='Field Service task created and linked: %s' % task.display_name)
        return True

    def action_view_fieldservice_task(self):
        self.ensure_one()
        if not self.fieldservice_task_id:
            return {'type': 'ir.actions.act_window_close'}
        return {
            'type': 'ir.actions.act_window',
            'name': self.fieldservice_task_id.display_name,
            'res_model': 'project.task',
            'res_id': self.fieldservice_task_id.id,
            'view_mode': 'form',
        }
