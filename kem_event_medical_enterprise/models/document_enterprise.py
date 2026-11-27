"""Push a document record into the Enterprise Documents app."""
from odoo import fields, models


class KemDocumentRecord(models.Model):
    _inherit = 'kem.document.record'

    documents_document_id = fields.Many2one('documents.document', 'Documents App File', readonly=True, copy=False)

    def action_push_to_documents(self):
        Document = self.env['documents.document'].sudo()
        for record in self:
            if record.documents_document_id:
                continue
            folder = self.env['documents.folder'].sudo().search(
                [('name', '=', 'Event Medical Services')], limit=1)
            if not folder:
                Folder = self.env['documents.folder'].sudo()
                values = {'name': 'Event Medical Services'}
                if 'company_id' in Folder._fields:
                    values['company_id'] = record.company_id.id
                folder = Folder.create(values)
            vals = {
                'name': record.name,
                'folder_id': folder.id,
                'kem_booking_id': record.booking_id.id,
                'kem_job_id': record.job_id.id,
            }
            if 'company_id' in Document._fields:
                vals['company_id'] = record.company_id.id
            if record.attachment_id:
                vals['attachment_id'] = record.attachment_id.id
            if 'res_model' in Document._fields and record.booking_id:
                vals.update({'res_model': 'kem.event.booking', 'res_id': record.booking_id.id})
            record.documents_document_id = Document.create(vals)
        return True
