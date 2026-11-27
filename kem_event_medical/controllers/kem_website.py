"""Public website enquiry form -> CRM opportunity + draft event booking."""
from odoo import http
from odoo.http import request


EVENT_TYPES = [
    ('sporting', 'Sporting event'),
    ('corporate', 'Corporate event'),
    ('community', 'Community event'),
    ('private', 'Private event'),
    ('construction', 'Construction project'),
    ('conference', 'Conference / exhibition'),
    ('other', 'Other'),
]


class KemWebsiteEnquiry(http.Controller):

    @http.route('/event-medical/enquire', type='http', auth='public', website=True)
    def enquiry_form(self, **kw):
        return request.render('kem_event_medical.kem_enquiry_form', {
            'event_types': EVENT_TYPES,
        })

    @http.route('/event-medical/enquire/submit', type='http', auth='public',
                website=True, methods=['POST'], csrf=True)
    def enquiry_submit(self, **post):
        values = {key: (post.get(key) or '').strip() for key in (
            'contact_name', 'email', 'phone', 'company', 'event_name',
            'event_type', 'event_date', 'location', 'attendance',
            'service_hours', 'requirements',
        )}
        partner = self._find_partner(values)
        source = request.env.ref('kem_event_medical.utm_source_website_enquiry', raise_if_not_found=False)
        stage = request.env.ref('kem_event_medical.stage_new_enquiry', raise_if_not_found=False)

        lead_vals = {
            'name': '%s — %s' % (values['event_name'] or 'Event medical enquiry',
                                values['company'] or values['contact_name'] or 'Website enquiry'),
            'contact_name': values['contact_name'],
            'email_from': values['email'],
            'phone': values['phone'],
            'partner_name': values['company'],
            'partner_id': partner.id if partner else False,
            'type': 'opportunity',
            'description': self._description(values),
            'source_id': source.id if source else False,
        }
        if stage:
            lead_vals['stage_id'] = stage.id
        lead = request.env['crm.lead'].sudo().create(lead_vals)

        booking_vals = {
            'name': values['event_name'] or 'Website enquiry',
            'partner_id': partner.id if partner else False,
            'opportunity_id': lead.id,
            'event_type': values['event_type'] if values['event_type'] in dict(EVENT_TYPES) else 'other',
            'location': values['location'],
            'start_date': values['event_date'] or False,
            'attendance': self._integer(values['attendance']),
            'requirement': values['requirements'],
            'service_start': self._time(values['service_hours'], 0),
            'service_end': self._time(values['service_hours'], 1),
            'state': 'enquiry',
            'company_id': request.env.company.id,
            'notes': 'Captured from the public website enquiry form.',
        }
        booking = request.env['kem.event.booking'].sudo().create(booking_vals)
        lead.sudo().write({'kem_booking_id': booking.id})
        return request.redirect('/event-medical/enquire/thanks?ref=%s' % booking.reference)

    @http.route('/event-medical/enquire/thanks', type='http', auth='public', website=True)
    def enquiry_thanks(self, **kw):
        return request.render('kem_event_medical.kem_enquiry_thanks', {
            'reference': kw.get('ref') or '',
        })

    @staticmethod
    def _integer(text):
        try:
            return int(text)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _time(text, index):
        try:
            parts = (text or '').split('-')
            return parts[index].strip()[:5]
        except (IndexError, AttributeError):
            return ''

    @staticmethod
    def _description(values):
        return '\n'.join([
            'Website enquiry received.',
            'Event: %s' % (values['event_name'] or '—'),
            'Type: %s' % (values['event_type'] or '—'),
            'Date: %s' % (values['event_date'] or '—'),
            'Location: %s' % (values['location'] or '—'),
            'Attendance: %s' % (values['attendance'] or '—'),
            'Service hours: %s' % (values['service_hours'] or '—'),
            '',
            values['requirements'],
        ])

    @staticmethod
    def _find_partner(values):
        Partner = request.env['res.partner'].sudo()
        email = values['email']
        if email:
            partner = Partner.search([('email', '=', email)], limit=1)
            if partner:
                return partner
        name = values['company'] or values['contact_name']
        if not name:
            return False
        return Partner.create({
            'name': name,
            'email': email,
            'phone': values['phone'],
            'customer_rank': 1,
            'comment': 'Created from a public website enquiry.',
        })
