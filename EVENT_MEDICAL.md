# Event Medical Services addons

Two addons were added to this repository for the emergency response / event
medical demonstration. They follow the same convention as the car rental
modules: a core addon that stays installable on Community, and a separate
Enterprise bridge.

| Addon | Folder | Installable | Purpose |
|---|---|---|---|
| Event Medical Services | `kem_event_medical` | Yes | Event bookings, operational jobs, document records, dashboard |
| Event Medical - Enterprise Bridge | `kem_event_medical_enterprise` | Yes (Enterprise / Odoo.sh only) | Planning, Field Service, Documents and Sign integration |

## How the apps communicate

The core addon never imports an Enterprise module. It exposes three hooks that
the bridge overrides:

| Core hook | Enterprise action |
|---|---|
| `booking._enterprise_on_confirm()` | Creates a booking confirmation file in **Documents** |
| `booking._enterprise_create_planning_slots()` | Creates a **Planning** slot per assigned employee |
| `booking._enterprise_on_complete()` | Publishes the service report to **Documents**, refreshes Sign |
| `job._enterprise_create_fsm_task()` | Creates a linked **Field Service** task (`project.task`) |

Standard Odoo links carry the rest of the flow:

```
CRM opportunity ──► booking ──► quotation (sale.order) ──► invoice (account.move)
                      ├──► hr.employee team ──► planning.slot
                      ├──► fleet.vehicle ──► field service task
                      ├──► project.project / project.task
                      └──► kem.document.record ──► documents.document / sign.request
```

Native records carry `kem_booking_id` / `kem_job_id` link fields, so a user
starting in Planning, Field Service or Documents can navigate back to the
source record.

## Odoo.sh / Enterprise deployment

1. Push this repository to the Odoo.sh project (the two folders are ordinary addons).
2. Ensure the Enterprise apps **Planning**, **Field Service**, **Documents** and
   **Sign** are installed on the database.
3. Install **Event Medical Services**, then **Event Medical - Enterprise Bridge**.

If you ever use the repository on a **Community** database, keep the bridge
disabled: edit `kem_event_medical_enterprise/__manifest__.py` and set
`installable: False` (the same approach used for `car_rental_sign_bridge`).
The core addon installs and works without the bridge.

## Demonstration data

`kem_event_medical/demo/demo_data.xml` contains fictional customers, CRM
opportunities, service products, quotations, crew, vehicles, bookings, jobs and
document records. It is loaded only when Odoo demo data is enabled, so a
production database stays clean.

## Files

```
kem_event_medical/
  models/booking.py          Event booking hub + integration hooks
  models/job.py              Operational job workflow
  models/document.py         Document register
  models/dashboard.py        Live management figures
  security/                  Groups, access rights, company record rules
  views/                     Bookings, jobs, documents, dashboard, navigation
  data/                      Sequences, CRM pipeline stages
  demo/                      Fictional demonstration records

kem_event_medical_enterprise/
  models/native_links.py     Link fields on planning.slot / project.task / documents.document
  models/booking_enterprise.py   Planning, Documents, Sign + hook implementations
  models/job_enterprise.py       Field Service task creation
  models/document_enterprise.py  Push to Documents app
  views/                     Extended forms + connected-app menus
```
