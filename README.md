# City Delights Car Rental for Odoo 19

This repository contains `car_rental_management_odoo`, the customised car rental addon maintained by Clinton Giri. Other local addons are excluded.

Features include vehicle photos, destination pricing, bookings, rental payments, security deposits, signed inspections and agreements, damage recovery, maintenance and Odoo accounting integration.

## Run locally

For the existing Windows development setup, double-click **Start Odoo.cmd** or run `./start-odoo.ps1` in PowerShell. PostgreSQL must be running. Open http://127.0.0.1:8069.

For a different machine, configure your Python environment, Odoo 19 installation and `addons_path`; adapt the launcher paths as needed. Keep configuration, credentials, filestore and backups outside this repository.

## Install and upgrade

Install `car_rental_management_odoo` through Odoo Apps. After code or view changes, stop the server and upgrade:

```text
python /path/to/odoo-bin -c /path/to/odoo.conf -d your_database -u car_rental_management_odoo --stop-after-init
```

Run the workflow tests against a development database:

```text
python /path/to/odoo-bin -c /path/to/odoo.conf -d your_test_database -u car_rental_management_odoo --test-enable --test-tags /car_rental_management_odoo --stop-after-init
```

## User guides

- [How It Works](car_rental_management_odoo/docs/HOW_IT_WORKS.md)
- [Proposal implementation and configuration](car_rental_management_odoo/docs/PROPOSAL_IMPLEMENTATION.md)

Pricing, fleet compliance, accounting accounts/journals and approved agreement terms must be configured for your company. The security deposit defaults to one daily rate and cannot be below 50%. The module records payments; it does not transfer money automatically.

## License and attribution

LGPL-3. This module is adapted from Oumaima's Car Rental Management addon. Original source attribution is retained here; the current customisation is maintained by Clinton Giri.
