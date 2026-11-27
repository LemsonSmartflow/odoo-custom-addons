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
Maintenance, Project, Accounting, Expenses, Website and Website CRM.

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

## Website lead capture

Public page: **`/event-medical/enquire`** (also linked in the website top menu
as "Request Medical Cover"). The form collects contact details, event type,
date, venue, attendance, service hours and requirements. On submit it creates:

1. a `crm.lead` opportunity in the **New Enquiry** stage, tagged with the
   `Website Enquiry` UTM source, and
2. a draft `kem.event.booking` linked to that opportunity.

**Event Medical → Website Leads** shows only those website opportunities. From
the list you can qualify them using the **Create Event Medical Booking** server
action, which turns an opportunity into a booking for the scheduling workflow.
This is the lead-mining / opportunity hand-off in the demonstration.

Standard Odoo links carry the rest of the flow:

```
Website form ──► CRM opportunity ──► booking ──► quotation ──► invoice
                      ▲
                      └── Website Leads queue (lead mining)
```

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
