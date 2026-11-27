"""Push a document record into the Enterprise Documents app."""
from odoo import fields, models
from odoo.exceptions import UserError


class KemDocumentRecord(models.Model):
    _inherit = 'kem.document.record'

    documents_document_id = fields.Many2one('documents.document', 'Documents App File', readonly=True, copy=False)

    def action_push_to_documents(self):
        if 'documents.document' not in self.env:
            raise UserError(
                'The Documents app is not available on this database. '
                'Install/upgrade the Enterprise Documents application and then '
                'upgrade the Event Medical Services module.'
            )
        Document = self.env['documents.document'].sudo()
        has_folder_model = 'documents.folder' in self.env
        for record in self:
            if record.documents_document_id:
                continue
            folder = False
            if has_folder_model:
                Folder = self.env['documents.folder'].sudo()
                folder = Folder.search([('name', '=', 'Event Medical Services')], limit=1)
                if not folder:
                    values = {'name': 'Event Medical Services'}
                    if 'company_id' in Folder._fields:
                        values['company_id'] = record.company_id.id
                    folder = Folder.create(values)
            vals = {
                'name': record.name,
                'kem_booking_id': record.booking_id.id,
                'kem_job_id': record.job_id.id,
            }
            if folder and 'folder_id' in Document._fields:
                vals['folder_id'] = folder.id
            if 'company_id' in Document._fields:
                vals['company_id'] = record.company_id.id
            if record.attachment_id:
                vals['attachment_id'] = record.attachment_id.id
            if 'res_model' in Document._fields and record.booking_id:
                vals.update({'res_model': 'kem.event.booking', 'res_id': record.booking_id.id})
            record.documents_document_id = Document.create(vals)
        return True
