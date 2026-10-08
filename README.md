# Odoo Custom Addons

Custom addons for Odoo 19.

| Directory | Author | Purpose |
| --- | --- | --- |
| `car_rental_management_odoo` | Oumaima | Vehicle photos and gallery, customers, reservations, rentals, instalment payments, and a connected dashboard. |
| `car_rental_management` | City Delights (Pty) Ltd | Destination pricing, fleet allocation, inspections, deposits, damage recovery, and accounting integration. |

Both modules display as **Car Rental Management** in Odoo. Check the technical name and author before installing. The City Delights addon is preserved here but is currently uninstalled in the local development database.

## Installation

1. Clone this repository into your Odoo custom addons directory.
2. Add the repository's absolute path to `addons_path` in your local Odoo configuration, alongside the standard addons paths.
3. Restart Odoo, enable developer mode, and run **Apps → Update Apps List**.
4. Install the desired module. For `car_rental_management_odoo`, grant users **Car Rental → Agent** or **Administrator** access under **Settings → Users**.

Keep your database passwords, Odoo configuration, filestore, and database backups outside this repository.

## Connected rental workflow

Open **Car Rental → Vehicles** to browse photo cards or upload vehicle photos. Create customers with valid driving licence details, then reserve a vehicle, confirm the reservation, and select **Create Rental**. Enter pickup mileage, start the rental, and use **Record Payment** to register instalments. The rental shows total paid, outstanding balance, and payment history. At return, enter final mileage and select **Return Vehicle**.

Payments in this addon are internal rental payment records; they do not collect money through a payment gateway or create accounting entries.

## Upgrade and test

Use the Python environment installed for your Odoo server:

```text
python /path/to/odoo-bin -c /path/to/odoo.conf -d your_database -u car_rental_management_odoo --stop-after-init
python /path/to/odoo-bin -c /path/to/odoo.conf -d your_test_database -u car_rental_management_odoo --test-enable --test-tags /car_rental_management_odoo --stop-after-init
```

Stop other Odoo processes using the database before upgrading, then restart the server afterward. Run tests against a development or test database.

The connected workflow tests cover reservation-to-rental creation, instalments, overpayment protection, pickup and return, linked reservation protection, and navigation/views.

## License and attribution

Both addon manifests declare LGPL-3. Original authors are retained in their manifests. `car_rental_management_odoo` is adapted from Oumaima's Car Rental Management addon, with local improvements to views, vehicle previews, and connected workflows.
