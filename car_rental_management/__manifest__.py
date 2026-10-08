# Part of Odoo. See LICENSE file for full copyright and licensing details.
{
    'name': 'Car Rental Management',
    'version': '0.1',
    'sequence': 90,
    'category': 'Sales/Sales',
    'website': 'https://www.citydelights.co.bw',
    'summary': 'End-to-end car rental: destination pricing, fleet allocation, inspections, deposits, damage recovery',
    'description': """
Car Rental Management
=====================
Destination-based rental pricing engine, vehicle allocation with double-booking
protection, mandatory pickup/return inspections, refundable security deposits
(liability accounting), damage assessment and recovery, late-return charges,
fleet compliance (insurance / road licence / fitness / tracker) and reporting.

Built for City Delights (Pty) Ltd per the approved developer specification.
""",
    'depends': [
        'sale_management',
        'fleet',
        'account',
        'mail',
        'maintenance',
        'website',
    ],
    'data': [
        'security/car_rental_security.xml',
        'security/ir.model.access.csv',
        'views/destination_views.xml',
        'views/vehicle_category_views.xml',
        'views/pricing_rule_views.xml',
        'views/fleet_vehicle_views.xml',
        'views/rental_order_views.xml',
        'views/rental_inspection_views.xml',
        'views/rental_damage_views.xml',
        'views/rental_deposit_views.xml',
        'views/rental_charge_views.xml',
        'views/product_template_views.xml',
        'views/res_partner_views.xml',
        'views/maintenance_request_views.xml',
        'views/res_config_settings_views.xml',
        'views/reporting_views.xml',
        'views/car_rental_menus.xml',
        'views/website_templates.xml',
        'data/sequences.xml',
        'data/cron.xml',
        'data/mail_templates.xml',
        'reports/rental_reports.xml',
    ],
    'demo': [
        'demo/demo_data.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': True,
    'author': 'City Delights (Pty) Ltd',
    'assets': {},
    'license': 'LGPL-3',
}
