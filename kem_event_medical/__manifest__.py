{
    'name': 'Event Medical Services',
    'version': '19.0.1.0.0',
    'summary': 'Emergency response and event medical bookings, jobs and records',
    'category': 'Services',
    'author': 'Smartflow',
    'license': 'LGPL-3',
    'description': """
Event Medical Services — core application.

Adds event booking and operational job records on top of the standard Odoo
applications (CRM, Sales, Employees, Fleet, Inventory, Maintenance, Project,
Accounting and Expenses). It is deliberately free of any Enterprise-only
reference so it installs on Community as well as Enterprise / Odoo.sh.

Enterprise integrations (Planning, Field Service, Documents and Sign) live in
the separate `kem_event_medical_enterprise` addon in this repository.
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
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/sequences.xml',
        'data/pipeline_stages.xml',
        'views/booking_views.xml',
        'views/job_views.xml',
        'views/document_views.xml',
        'views/dashboard_views.xml',
        'views/navigation_views.xml',
    ],
    'demo': [
        'demo/demo_data.xml',
    ],
    'application': True,
    'installable': True,
}
