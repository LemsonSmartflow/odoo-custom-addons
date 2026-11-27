"""Link fields added to native Enterprise models.

Keeping the links on the native records means a user can start from Planning,
Field Service or Documents and still reach the originating booking/job.
"""
from odoo import fields, models


class PlanningSlot(models.Model):
    _inherit = 'planning.slot'

    kem_booking_id = fields.Many2one('kem.event.booking', 'Event Medical Booking', ondelete='set null', index=True)
    kem_job_id = fields.Many2one('kem.operational.job', 'Operational Job', ondelete='set null', index=True)


class ProjectTask(models.Model):
    _inherit = 'project.task'

    kem_booking_id = fields.Many2one('kem.event.booking', 'Event Medical Booking', ondelete='set null', index=True)
    kem_job_id = fields.Many2one('kem.operational.job', 'Operational Job', ondelete='set null', index=True)


class DocumentsDocument(models.Model):
    _inherit = 'documents.document'

    kem_booking_id = fields.Many2one('kem.event.booking', 'Event Medical Booking', ondelete='set null', index=True)
    kem_job_id = fields.Many2one('kem.operational.job', 'Operational Job', ondelete='set null', index=True)
