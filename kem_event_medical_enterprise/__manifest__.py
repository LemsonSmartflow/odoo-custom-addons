{
    'name': 'Event Medical - Enterprise Bridge',
    'version': '19.0.1.0.0',
    'summary': 'Planning, Field Service, Documents and Sign integration for Event Medical Services',
    'category': 'Services',
    'license': 'LGPL-3',
    'author': 'Smartflow',
    'depends': [
        'kem_event_medical',
        'planning',
        'fieldservice',
        'documents',
        'sign',
    ],
    'data': [
        'views/booking_enterprise_views.xml',
        'views/job_enterprise_views.xml',
        'views/document_enterprise_views.xml',
        'views/navigation_enterprise_views.xml',
    ],
    'description': """
Enterprise integration for Event Medical Services.

Synchronises bookings and jobs with Planning slots, Field Service tasks,
the Documents app and Odoo Sign. The core addon contains no Enterprise
reference and all hooks degrade gracefully if this bridge is not installed.

Requires an Enterprise / Odoo.sh database with Planning, Field Service,
Documents and Sign installed. On a Community database set installable to
False (or simply do not deploy this folder) - the core addon still works.
    """,
    'installable': True,
    'application': False,
}
