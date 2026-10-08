{
    'name': 'Car Rental Management',
    'version': '19.0.2.0.0',
    'summary': 'Car Rental Management Application',
    'category': 'Services',
    'author': 'Oumaima',
    'license': 'LGPL-3',

    'depends': [
        'base',
    ],

    'data': [
        'data/sequences.xml',
        'security/security.xml',
        'security/ir.model.access.csv',
        'views/customer_views.xml',
        'views/vehicle_views.xml',
        'views/reservation_views.xml',
        'views/rental_views.xml',
        'views/payment_views.xml',
        'views/dashboard_views.xml',
        'views/connected_views.xml',
    ],

    'application': True,
    'assets': {
        'web.assets_backend': ['car_rental_management_odoo/static/src/scss/rental.scss'],
    },
    'installable': True,
}
