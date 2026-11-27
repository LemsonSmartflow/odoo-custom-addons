"""Document register — a lightweight core record with an Enterprise bridge."""
from odoo import fields, models


class KemDocumentRecord(models.Model):
    _name = 'kem.document.record'
    _description = 'Event Medical Document Record'
    _order = 'date desc, id desc'

    name = fields.Char('Document Name', required=True)
    reference = fields.Char('Reference', readonly=True, copy=False)
    company_id = fields.Many2one('res.company', 'Company', default=lambda self: self.env.company, required=True)
    category = fields.Selection([
        ('contract', 'Service contract'),
        ('quotation', 'Customer quotation'),
        ('booking', 'Booking confirmation'),
        ('vehicle', 'Vehicle document'),
        ('employee', 'Employee document'),
        ('report', 'Service report'),
        ('purchase', 'Purchase documentation'),
        ('invoice', 'Invoice documentation'),
    ], 'Category', default='report')
    partner_id = fields.Many2one('res.partner', 'Linked Customer', index=True)
    booking_id = fields.Many2one('kem.event.booking', 'Related Booking', ondelete='set null')
    job_id = fields.Many2one('kem.operational.job', 'Related Job', ondelete='set null')
    attachment_id = fields.Many2one('ir.attachment', 'File', ondelete='set null')
    date = fields.Date('Date', default=fields.Date.context_today)
    access_level = fields.Char('Access', help='Who should be able to see this record in a live deployment')
    notes = fields.Text('Notes')

    def action_open_file(self):
        self.ensure_one()
        if not self.attachment_id:
            return {'type': 'ir.actions.act_window_close'}
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=true' % self.attachment_id.id,
            'target': 'new',
        }
