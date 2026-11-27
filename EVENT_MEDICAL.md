# Event Medical Services addon

The demonstration is provided as **one single Odoo addon**: `kem_event_medical`.
It sits alongside the untouched car rental addons at the repository root.

```
car_rental_management_odoo/
car_rental_sign_bridge/
kem_event_medical/            <-- the Event Medical addon
compose.yaml
```

There is no second Event Medical module. Odoo.sh therefore has only one new
addon to install from this repository.

## Dependencies

Standard applications: CRM, Sales, Contacts, Employees, Fleet, Inventory,
Maintenance, Project, Accounting and Expenses.

Enterprise applications: **Planning**, **Documents** and **Sign**.

**Field Service is optional.** The separate `fieldservice` app is not a
dependency. When it is available, operational jobs also create linked Field
Service tasks; when it is not, the job workflow still works.

## How the apps communicate

The addon exposes hooks that synchronise the custom records with Enterprise
apps:

| Hook | Action |
|---|---|
| `booking._enterprise_on_confirm()` | Creates a booking confirmation file in **Documents** |
| `booking._enterprise_create_planning_slots()` | Creates a **Planning** slot per assigned employee |
| `booking._enterprise_on_complete()` | Publishes the service report to **Documents**, refreshes Sign |
| `job._enterprise_create_fsm_task()` | Creates a linked **Field Service** task when `fieldservice` is installed |

Standard Odoo links carry the rest of the flow:

```
CRM opportunity ──► booking ──► quotation (sale.order) ──► invoice (account.move)
                      ├──► hr.employee team ──► planning.slot
                      ├──► fleet.vehicle ──► field service task (optional)
                      ├──► project.project / project.task
                      └──► kem.document.record ──► documents.document / sign.request
```

## Odoo.sh deployment

1. Push this repository.
2. Install / ensure **Planning**, **Documents** and **Sign** are available.
3. Install **Event Medical Services**.

The fictional sample records are in `demo/demo_data.xml` and load only when
demo data is enabled on the database.

## Source layout

```
kem_event_medical/
  models/booking.py                 Event booking hub + integration hooks
  models/job.py                     Operational job workflow
  models/document.py                Document register
  models/dashboard.py               Live management figures
  models/enterprise_*.py            Enterprise synchronisation and link fields
  security/                         Groups, access rights, company record rules
  views/                            Bookings, jobs, documents, dashboard, navigation,
                                    plus Enterprise form extensions
  data/                             Sequences, CRM pipeline stages
  demo/                             Fictional demonstration records
```
