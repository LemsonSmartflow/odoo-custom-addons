"""Website enquiries can be qualified and converted into event bookings."""
from odoo import fields, models


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    kem_booking_id = fields.Many2one('kem.event.booking', 'Event Medical Booking',
                                     ondelete='set null', readonly=True, copy=False)

    def action_create_kem_booking(self):
        """Server action used from the Website Enquiries list (lead mining)."""
        for lead in self:
            if lead.kem_booking_id:
                continue
            booking = self.env['kem.event.booking'].create({
                'name': lead.name,
                'partner_id': lead.partner_id.id,
                'opportunity_id': lead.id,
                'event_type': 'other',
                'requirement': lead.description,
                'state': 'enquiry',
                'company_id': lead.company_id.id if 'company_id' in lead._fields else self.env.company.id,
                'notes': 'Created from a CRM opportunity.',
            })
            lead.kem_booking_id = booking.id
        return True

    def action_view_kem_booking(self):
        self.ensure_one()
        if not self.kem_booking_id:
            return {'type': 'ir.actions.act_window_close'}
        return {
            'type': 'ir.actions.act_window',
            'name': self.kem_booking_id.name,
            'res_model': 'kem.event.booking',
            'res_id': self.kem_booking_id.id,
            'view_mode': 'form',
        }
