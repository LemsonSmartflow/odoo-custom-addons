{
    'name': 'Event Medical Services',
    'version': '19.0.3.0.0',
    'summary': 'Emergency response and event medical bookings, jobs and records',
    'category': 'Services',
    'author': 'Smartflow',
    'license': 'LGPL-3',
    'description': """
Event Medical Services — single application addon.

Adds event booking and operational job records on top of the standard Odoo
applications (CRM, Sales, Employees, Fleet, Inventory, Maintenance, Project,
Accounting and Expenses). Enterprise integrations (Planning, Documents and
Sign) are included in this same addon. Field Service is optional: when the
separate `fieldservice` app is available, jobs also create Field Service
tasks; otherwise the job workflow works without it.

A public website page (/event-medical/enquire) captures enquiries into CRM
opportunities and draft event bookings, with a Website Leads queue for
qualification.

All demonstration records are fictional.
    """,
    'depends': [
        'base',
        'mail',
        'contacts',
        'crm',
        'sale_management',
        'hr',
        'fleet',
        'stock',
        'maintenance',
        'project',
        'account',
        'hr_expense',
        'website',
        'website_crm',
        'planning',
        'documents',
        'sign',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/sequences.xml',
        'data/pipeline_stages.xml',
        'data/website_leads.xml',
        'views/booking_views.xml',
        'views/job_views.xml',
        'views/document_views.xml',
        'views/dashboard_views.xml',
        'views/navigation_views.xml',
        'views/enterprise_booking_views.xml',
        'views/enterprise_job_views.xml',
        'views/enterprise_document_views.xml',
        'views/enterprise_navigation_views.xml',
        'views/crm_leads_views.xml',
        'views/website_templates.xml',
    ],
    'demo': [
        'demo/demo_data.xml',
    ],
    'application': True,
    'installable': True,
}
