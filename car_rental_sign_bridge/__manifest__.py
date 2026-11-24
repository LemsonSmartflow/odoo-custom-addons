{
    'name': 'Car Rental - Odoo Sign Bridge',
    'version': '19.0.1.0.0',
    'summary': 'Optional Odoo Sign backend for Car Rental agreements',
    'category': 'Services',
    'license': 'LGPL-3',
    'author': 'Clinton Giri',
    'depends': ['car_rental_management_odoo', 'sign'],
    'data': [],
    # Disabled by default: Odoo.sh auto-installs every addon in the repository,
    # and this bridge requires the Enterprise-only `sign` module.  Set to True
    # only on an Enterprise instance where Sign is installed.
    'installable': False,
    'application': False,
}
