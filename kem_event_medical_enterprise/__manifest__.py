{
    'name': 'Event Medical - Enterprise Bridge',
    'version': '19.0.1.0.0',
    'summary': 'Planning, Documents and Sign integration for Event Medical Services (Field Service optional)',
    'category': 'Services',
    'license': 'LGPL-3',
    'author': 'Smartflow',
    'depends': [
        'kem_event_medical',
        'planning',
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

Synchronises bookings and jobs with Planning slots, the Documents app and
Odoo Sign. Field Service is optional: if the separate `fieldservice` app is
available, operational jobs also create linked Field Service tasks; if not,
the job workflow still works without it.

Requires an Enterprise / Odoo.sh database with Planning, Documents and Sign
available. On a Community database set installable to False (or simply do not
deploy this folder) - the core addon still works.
    """,
    'installable': True,
    'application': False,
}
